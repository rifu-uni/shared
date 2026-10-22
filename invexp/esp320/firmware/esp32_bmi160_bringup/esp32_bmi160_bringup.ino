#include <Arduino.h>
#include <Wire.h>
#include <ctype.h>

#include "bmi160.h"
#include "tca9548a.h"

constexpr uint8_t kSdaPin = 8;
constexpr uint8_t kSclPin = 9;
constexpr uint32_t kI2cFrequency = 100000;
constexpr uint8_t kMuxAddress = 0x70;
constexpr uint8_t kFirstBmiAddress = 0x68;
constexpr uint8_t kSecondBmiAddress = 0x69;
constexpr uint8_t kUpstreamCapacity = 16;
constexpr uint8_t kMuxScanCapacity = 8;
constexpr uint32_t kStreamIntervalMs = 100;

const char* const kFirmwareName = "ESP32-S3 BMI160 + TCA9548A bring-up";
const char* const kFirmwareVersion = "1.0.0";

struct DetectedConfig {
  bool muxPresent;
  bool directPresent;
  uint8_t directAddress;
  uint8_t upstreamAddresses[kUpstreamCapacity];
  uint8_t upstreamCount;
  bool channelHasBmi[8];
  uint8_t channelAddress[8];
  bool muxSensorPresent;
  bool muxSensorReady;
  bool directSensorReady;
  uint8_t firstMuxChannel;
};

struct StreamState {
  bool active;
  bool viaMux;
  uint8_t channel;
  Bmi160* sensor;
  uint32_t lastSampleMs;
};

DetectedConfig config = {};
StreamState stream = {false, false, 0, nullptr, 0};

Bmi160 directSensor;
Bmi160 muxSensor;
Tca9548a mux;

void resetConfig();
void clearMuxSensors();
void printBanner();
void printHelp();
void printConfigSummary();
void printInfo();
void printSample(const Bmi160Sample& sample);
void printAddressList(const uint8_t* addresses, uint8_t count);
void printMuxMissing();
void printBmiNotFound(const char* location);
const char* deviceName(uint8_t address);
uint8_t scanBus(uint8_t* addresses, uint8_t capacity);
void updateConfigFromUpstreamScan(const uint8_t* found, uint8_t count);
void scanUpstream();
void scanMuxChannels();
bool ensureMux();
bool initDirectSensor();
bool initMuxSensor(uint8_t channel);
bool initAnyMuxSensor();
void recomputeMuxPresence();
bool readOnce(Bmi160& sensor, bool viaMux, uint8_t channel);
void printSensorHealth(const char* label, Bmi160& sensor, bool viaMux, uint8_t channel);
void startStream();
void stopStream();
void serviceStream();
void handleCommand(char raw);
void detectAtBoot();

void setup() {
  Serial.begin(115200);
  delay(50);

  resetConfig();
  printBanner();

  Wire.begin(kSdaPin, kSclPin, kI2cFrequency);
  Wire.setTimeOut(50);
  Serial.println("[init] I2C started at 100 kHz; scanning upstream bus...");

  detectAtBoot();
  Serial.println("[init] ready. Type ? for commands.");
}

void loop() {
  while (Serial.available() > 0) {
    handleCommand(static_cast<char>(Serial.read()));
  }
  serviceStream();
}

void resetConfig() {
  config.muxPresent = false;
  config.directPresent = false;
  config.directAddress = 0;
  config.upstreamCount = 0;
  config.muxSensorPresent = false;
  config.muxSensorReady = false;
  config.directSensorReady = false;
  config.firstMuxChannel = 0;
  for (uint8_t i = 0; i < kUpstreamCapacity; ++i) {
    config.upstreamAddresses[i] = 0;
  }
  for (uint8_t channel = 0; channel < 8; ++channel) {
    config.channelHasBmi[channel] = false;
    config.channelAddress[channel] = 0;
  }
}

void clearMuxSensors() {
  config.muxSensorPresent = false;
  config.muxSensorReady = false;
  config.firstMuxChannel = 0;
  for (uint8_t channel = 0; channel < 8; ++channel) {
    config.channelHasBmi[channel] = false;
    config.channelAddress[channel] = 0;
  }
}

void printBanner() {
  Serial.println();
  Serial.println("============================================================");
  Serial.printf(" %s v%s\n", kFirmwareName, kFirmwareVersion);
  Serial.println(" Board : ESP32-S3 DevKitC-1 N16R8 (16 MB flash, 8 MB PSRAM)");
#if ARDUINO_USB_CDC_ON_BOOT
  Serial.println(" Serial: native USB CDC @115200");
#else
  Serial.println(" Serial: UART0 through CH343 @115200 (native USB CDC disabled)");
#endif
  Serial.println(" I2C   : SDA=GPIO8 SCL=GPIO9 @100 kHz");
  Serial.println(" Scale : accel raw/16384.0 -> g (+/-2 g)");
  Serial.println("         gyro  raw/16.4    -> dps (+/-2000 dps)");
  Serial.println("============================================================");
  printHelp();
}

void printHelp() {
  Serial.println("Commands (single letter, case-insensitive):");
  Serial.println("  s  scan upstream/direct I2C bus");
  Serial.println("  m  scan all 8 mux channels (one line per channel)");
  Serial.println("  d  read BMI160 directly on GPIO8/GPIO9 (0x68 or 0x69)");
  Serial.println("  0  read BMI160 through mux channel 0");
  Serial.println("  r  start streaming accel+gyro at 10 Hz");
  Serial.println("  x  stop streaming");
  Serial.println("  i  print detected configuration, chip IDs and addresses");
  Serial.println("  ?  this help");
}

void printConfigSummary() {
  Serial.println("------------------------------------------------------------");

  if (config.muxPresent) {
    Serial.print("[cfg ] TCA9548A at 0x70: present; BMI160 channels:");
    bool anySensor = false;
    for (uint8_t channel = 0; channel < 8; ++channel) {
      if (!config.channelHasBmi[channel]) {
        continue;
      }
      Serial.printf(" CH%u=0x%02X", channel, config.channelAddress[channel]);
      anySensor = true;
    }
    if (!anySensor) {
      Serial.print(" none (run m)");
    }
    Serial.println();
  } else {
    Serial.println("[cfg ] TCA9548A at 0x70: not found (direct mode still possible)");
  }

  if (config.directPresent) {
    Serial.printf("[cfg ] direct BMI160 at 0x%02X: %s", config.directAddress,
                  config.directSensorReady ? "ready" : "detected, not initialized");
    if (config.directSensorReady) {
      Serial.printf(" (chip ID 0x%02X)", directSensor.chipId());
    }
    Serial.println();
  } else {
    Serial.println("[cfg ] direct BMI160 at 0x68/0x69: not found");
  }

  if (config.muxSensorReady) {
    Serial.printf("[cfg ] mux target CH%u: BMI160 0x%02X ready (chip ID 0x%02X)\n",
                  config.firstMuxChannel, muxSensor.address(), muxSensor.chipId());
  } else if (config.muxSensorPresent) {
    Serial.println("[cfg ] mux BMI160 detected but not initialized; use 0 or r");
  }

  Serial.println("[cfg ] scales: accel raw/16384.0 -> g (+/-2 g); gyro raw/16.4 -> dps (+/-2000 dps)");

  if (!config.muxPresent && !config.directPresent) {
    printBmiNotFound("");
    Serial.println("[fail] no TCA9548A at 0x70 either; check RESET high, A0/A1/A2 to GND");
  }

  Serial.println("------------------------------------------------------------");
}

void printInfo() {
  Serial.println("[info] detected configuration:");
  printConfigSummary();

  if (config.directSensorReady) {
    printSensorHealth("direct", directSensor, false, 0);
  }
  if (config.muxSensorReady) {
    printSensorHealth("mux", muxSensor, true, config.firstMuxChannel);
  }

  if (stream.active) {
    Serial.printf("[info] stream: running at 10 Hz from %s\n",
                  stream.viaMux ? "mux" : "direct bus");
  } else {
    Serial.println("[info] stream: stopped");
  }
}

void printSample(const Bmi160Sample& sample) {
  Serial.printf(
      "[data] accel_g x=%+.3f y=%+.3f z=%+.3f | gyro_dps x=%+.3f y=%+.3f z=%+.3f\n",
      sample.accelG[0], sample.accelG[1], sample.accelG[2],
      sample.gyroDps[0], sample.gyroDps[1], sample.gyroDps[2]);
}

bool isBmi160At(uint8_t address) {
  if (address != kFirstBmiAddress && address != kSecondBmiAddress) {
    return false;
  }
  return Bmi160::probe(Wire, address);
}

const char* deviceName(uint8_t address) {
  if (address == kMuxAddress) {
    return "TCA9548A";
  }
  if (isBmi160At(address)) {
    return "BMI160";
  }
  return "unknown";
}

void printAddressList(const uint8_t* addresses, uint8_t count) {
  if (count == 0) {
    Serial.print(" none");
    return;
  }
  for (uint8_t i = 0; i < count; ++i) {
    Serial.printf(" 0x%02X (%s)", addresses[i], deviceName(addresses[i]));
  }
}

void printMuxMissing() {
  Serial.println(
      "[fail] TCA9548A not found at 0x70; check RESET tied high, A0/A1/A2 to GND, "
      "SDA/SCL, VIN/VCC, GND");
}

void printBmiNotFound(const char* location) {
  Serial.printf(
      "[fail] BMI160 not found at 0x68/0x69%s; check CS high, SA0 strap, SDA/SCL, VIN, GND\n",
      location);
}

uint8_t scanBus(uint8_t* addresses, uint8_t capacity) {
  uint8_t count = 0;
  for (uint8_t address = 0x08; address <= 0x77; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() != 0) {
      continue;
    }
    if (count < capacity) {
      addresses[count] = address;
      ++count;
    }
  }
  return count;
}

void updateConfigFromUpstreamScan(const uint8_t* found, uint8_t count) {
  bool muxSeen = false;
  bool directSeen = false;
  uint8_t directAddress = 0;

  config.upstreamCount = (count > kUpstreamCapacity) ? kUpstreamCapacity : count;
  for (uint8_t i = 0; i < config.upstreamCount; ++i) {
    config.upstreamAddresses[i] = found[i];
  }

  for (uint8_t i = 0; i < count; ++i) {
    if (found[i] == kMuxAddress) {
      muxSeen = true;
    }
    if (!directSeen && isBmi160At(found[i])) {
      directSeen = true;
      directAddress = found[i];
    }
  }

  if (muxSeen) {
    config.muxPresent = true;
  } else {
    config.muxPresent = false;
    clearMuxSensors();
  }

  if (directSeen) {
    if (!config.directPresent || config.directAddress != directAddress) {
      config.directSensorReady = false;
    }
    config.directPresent = true;
    config.directAddress = directAddress;
  } else {
    config.directPresent = false;
    config.directAddress = 0;
    config.directSensorReady = false;
  }
}

void scanUpstream() {
  // Silence the mux before scanning even when config is stale. Otherwise a channel
  // left selected by a previous run makes downstream sensors look like direct ones.
  const bool muxResponded = mux.begin(Wire, kMuxAddress);
  if (muxResponded && !mux.disableAll()) {
    Serial.printf("[warn] could not disable mux channels before scan: %s\n", mux.lastError());
  }

  uint8_t found[kUpstreamCapacity] = {};
  const uint8_t count = scanBus(found, kUpstreamCapacity);
  Serial.print("[scan] upstream bus:");
  printAddressList(found, count);
  Serial.println();

  updateConfigFromUpstreamScan(found, count);

  if (!config.muxPresent) {
    return;
  }

  if (!muxResponded) {
    Serial.printf("[fail] TCA9548A at 0x70 ACKed but control register read failed: %s\n",
                  mux.lastError());
    config.muxPresent = false;
    clearMuxSensors();
  }
}

void scanMuxChannels() {
  if (!config.muxPresent) {
    printMuxMissing();
    return;
  }

  const bool wasReady = config.muxSensorReady;
  const uint8_t readyChannel = config.firstMuxChannel;
  const uint8_t readyAddress = wasReady ? muxSensor.address() : 0;

  config.muxSensorPresent = false;
  config.muxSensorReady = false;
  config.firstMuxChannel = 0;
  for (uint8_t channel = 0; channel < 8; ++channel) {
    config.channelHasBmi[channel] = false;
    config.channelAddress[channel] = 0;
  }

  for (uint8_t channel = 0; channel < 8; ++channel) {
    uint8_t found[kMuxScanCapacity] = {};
    uint8_t count = 0;
    Serial.printf("[mux ] CH%u:", channel);

    if (!mux.scanChannel(channel, found, kMuxScanCapacity, count,
                         config.upstreamAddresses, config.upstreamCount)) {
      Serial.printf(" <scan failed: %s>", mux.lastError());
      Serial.println();
      continue;
    }

    printAddressList(found, count);
    Serial.println();

    for (uint8_t i = 0; i < count; ++i) {
      if (!isBmi160At(found[i])) {
        continue;
      }
      config.channelHasBmi[channel] = true;
      config.channelAddress[channel] = found[i];
      if (!config.muxSensorPresent) {
        config.muxSensorPresent = true;
        config.firstMuxChannel = channel;
      }
      break;
    }
  }

  if (wasReady && config.channelHasBmi[readyChannel] &&
      config.channelAddress[readyChannel] == readyAddress &&
      config.firstMuxChannel == readyChannel) {
    config.muxSensorReady = true;
  }
}

bool ensureMux() {
  if (!config.muxPresent) {
    printMuxMissing();
    return false;
  }

  if (!mux.begin(Wire, kMuxAddress)) {
    Serial.printf("[fail] TCA9548A control register error: %s\n", mux.lastError());
    config.muxPresent = false;
    clearMuxSensors();
    return false;
  }

  return true;
}

bool initDirectSensor() {
  if (config.muxPresent) {
    if (!mux.disableAll()) {
      Serial.printf("[warn] could not disable mux channels: %s\n", mux.lastError());
    }
  }

  for (uint8_t i = 0; i < 2; ++i) {
    const uint8_t address = (i == 0) ? kFirstBmiAddress : kSecondBmiAddress;
    if (!Bmi160::probe(Wire, address)) {
      continue;
    }

    config.directPresent = true;
    config.directAddress = address;
    if (!directSensor.begin(Wire, address)) {
      config.directSensorReady = false;
      Serial.printf("[fail] BMI160 at 0x%02X init failed: %s\n", address,
                    directSensor.lastError());
      return false;
    }

    config.directSensorReady = true;
    Serial.printf("[bmi ] direct BMI160 at 0x%02X ready (chip ID 0x%02X)\n", address,
                  directSensor.chipId());
    return true;
  }

  config.directPresent = false;
  config.directAddress = 0;
  config.directSensorReady = false;
  printBmiNotFound(" (direct bus)");
  return false;
}

bool initMuxSensor(uint8_t channel) {
  if (!config.muxPresent) {
    printMuxMissing();
    return false;
  }

  if (!mux.select(channel)) {
    Serial.printf("[fail] mux CH%u select failed: %s\n", channel, mux.lastError());
    return false;
  }

  for (uint8_t i = 0; i < 2; ++i) {
    const uint8_t address = (i == 0) ? kFirstBmiAddress : kSecondBmiAddress;

    // A direct-bus BMI160 also answers while a mux channel is selected. Do not
    // initialize it a second time as a mux sensor. Direct and mux devices must
    // not share an address; that topology is a bus collision and is rejected.
    if (config.directPresent && address == config.directAddress) {
      Serial.printf("[warn] mux CH%u: skipping direct-bus BMI160 at 0x%02X\n", channel, address);
      continue;
    }

    if (!Bmi160::probe(Wire, address)) {
      continue;
    }

    config.channelHasBmi[channel] = true;
    config.channelAddress[channel] = address;
    config.muxSensorPresent = true;

    if (!muxSensor.begin(Wire, address)) {
      config.muxSensorReady = false;
      Serial.printf("[fail] BMI160 at 0x%02X on mux CH%u init failed: %s\n", address, channel,
                    muxSensor.lastError());
      return false;
    }

    config.muxSensorReady = true;
    config.firstMuxChannel = channel;
    Serial.printf("[bmi ] mux CH%u BMI160 at 0x%02X ready (chip ID 0x%02X)\n", channel, address,
                  muxSensor.chipId());
    return true;
  }

  config.channelHasBmi[channel] = false;
  config.channelAddress[channel] = 0;
  config.muxSensorReady = false;
  recomputeMuxPresence();
  Serial.printf(
      "[fail] BMI160 not found at 0x68/0x69 on mux CH%u; check CS high, SA0 strap, "
      "SDA/SCL, VIN, GND\n",
      channel);
  return false;
}

void recomputeMuxPresence() {
  const uint8_t previousFirst = config.firstMuxChannel;
  bool anySensor = false;
  uint8_t firstChannel = 0;

  for (uint8_t channel = 0; channel < 8; ++channel) {
    if (!config.channelHasBmi[channel]) {
      continue;
    }
    if (!anySensor) {
      anySensor = true;
      firstChannel = channel;
    }
  }

  config.muxSensorPresent = anySensor;
  config.firstMuxChannel = firstChannel;
  if (config.muxSensorReady && previousFirst != firstChannel) {
    config.muxSensorReady = false;
  }
}

bool initAnyMuxSensor() {
  for (uint8_t channel = 0; channel < 8; ++channel) {
    if (!config.channelHasBmi[channel]) {
      continue;
    }
    if (initMuxSensor(channel)) {
      return true;
    }
  }
  return false;
}

bool readOnce(Bmi160& sensor, bool viaMux, uint8_t channel) {
  if (viaMux) {
    if (!mux.select(channel)) {
      Serial.printf("[fail] mux CH%u select failed: %s\n", channel, mux.lastError());
      return false;
    }
  } else if (config.muxPresent) {
    if (!mux.disableAll()) {
      Serial.printf("[warn] could not disable mux channels: %s\n", mux.lastError());
    }
  }

  Bmi160Raw raw = {};
  if (!sensor.readRaw(raw)) {
    Serial.printf("[fail] BMI160 0x%02X read failed: %s\n", sensor.address(),
                  sensor.lastError());
    return false;
  }

  printSample(Bmi160::convert(raw));
  return true;
}

void printSensorHealth(const char* label, Bmi160& sensor, bool viaMux, uint8_t channel) {
  if (viaMux) {
    if (!mux.select(channel)) {
      Serial.printf("[fail] mux CH%u select failed: %s\n", channel, mux.lastError());
      mux.disableAll();
      return;
    }
  }

  uint8_t status = 0;
  uint8_t error = 0;
  const bool statusOk = sensor.readStatus(status);
  const bool errorOk = sensor.readError(error);

  if (statusOk && errorOk) {
    Serial.printf("[info] %s 0x%02X: status=0x%02X error=0x%02X\n", label, sensor.address(),
                  status, error);
  } else {
    Serial.printf("[fail] %s 0x%02X health read failed: %s\n", label, sensor.address(),
                  sensor.lastError());
  }

  // A direct health read must not leave a mux channel selected from an earlier
  // command; otherwise the next direct scan also sees downstream devices.
  if (viaMux || config.muxPresent) {
    mux.disableAll();
  }
}

void startStream() {
  if (stream.active) {
    Serial.println("[stream] already running; send x to stop");
    return;
  }

  if (config.muxSensorPresent && (config.muxSensorReady || initAnyMuxSensor())) {
    stream.active = true;
    stream.viaMux = true;
    stream.channel = config.firstMuxChannel;
    stream.sensor = &muxSensor;
    Serial.printf("[stream] 10 Hz started: BMI160 0x%02X via mux CH%u; x stops\n",
                  muxSensor.address(), stream.channel);
  } else if (config.directPresent) {
    if (config.muxSensorPresent) {
      Serial.println("[warn] mux sensor unavailable; falling back to the direct bus");
    }
    if (!config.directSensorReady && !initDirectSensor()) {
      return;
    }
    stream.active = true;
    stream.viaMux = false;
    stream.channel = 0;
    stream.sensor = &directSensor;
    Serial.printf("[stream] 10 Hz started: BMI160 0x%02X direct; x stops\n",
                  directSensor.address());
  } else {
    Serial.println("[fail] no BMI160 detected; run s or m, then check wiring");
    return;
  }

  stream.lastSampleMs = millis() - kStreamIntervalMs;
}

void stopStream() {
  if (!stream.active) {
    return;
  }

  stream.active = false;
  stream.viaMux = false;
  stream.channel = 0;
  stream.sensor = nullptr;

  if (config.muxPresent) {
    mux.disableAll();
  }

  Serial.println("[stream] stopped");
}

void serviceStream() {
  if (!stream.active || stream.sensor == nullptr) {
    return;
  }

  const uint32_t now = millis();
  if (now - stream.lastSampleMs < kStreamIntervalMs) {
    return;
  }
  stream.lastSampleMs = now;

  if (stream.viaMux) {
    if (!mux.select(stream.channel)) {
      Serial.printf("[fail] mux CH%u select failed: %s\n", stream.channel, mux.lastError());
      stopStream();
      return;
    }
  } else if (config.muxPresent) {
    if (!mux.disableAll()) {
      Serial.printf("[fail] mux disable failed: %s\n", mux.lastError());
      stopStream();
      return;
    }
  }

  Bmi160Raw raw = {};
  if (!stream.sensor->readRaw(raw)) {
    Serial.printf("[fail] BMI160 0x%02X read failed: %s\n", stream.sensor->address(),
                  stream.sensor->lastError());
    stopStream();
    return;
  }

  printSample(Bmi160::convert(raw));
}

void handleCommand(char raw) {
  const char command = static_cast<char>(tolower(static_cast<unsigned char>(raw)));

  switch (command) {
    case '\r':
    case '\n':
    case ' ':
    case '\t':
      return;

    case 's':
      stopStream();
      scanUpstream();
      printConfigSummary();
      return;

    case 'm':
      stopStream();
      if (!ensureMux()) {
        return;
      }
      Serial.println("[mux ] scanning channels 0-7 (0x70 filtered from results)...");
      scanMuxChannels();
      mux.disableAll();
      printConfigSummary();
      return;

    case 'd':
      stopStream();
      initDirectSensor();
      if (config.directSensorReady) {
        readOnce(directSensor, false, 0);
      }
      return;

    case '0':
      stopStream();
      if (!ensureMux()) {
        return;
      }
      if (initMuxSensor(0)) {
        readOnce(muxSensor, true, 0);
      }
      mux.disableAll();
      printConfigSummary();
      return;

    case 'r':
      startStream();
      return;

    case 'x':
      if (!stream.active) {
        Serial.println("[stream] already stopped");
        return;
      }
      stopStream();
      return;

    case 'i':
      printInfo();
      return;

    case '?':
      printHelp();
      return;

    default:
      Serial.printf("[warn] unknown command '%c'; type ? for help\n", raw);
      return;
  }
}

void detectAtBoot() {
  scanUpstream();

  if (config.muxPresent) {
    Serial.println("[mux ] scanning channels 0-7 for BMI160...");
    scanMuxChannels();
    mux.disableAll();

    if (config.muxSensorPresent) {
      if (initAnyMuxSensor()) {
        mux.disableAll();
      }
    }
  }

  if (config.directPresent) {
    initDirectSensor();
  }

  printConfigSummary();
}
