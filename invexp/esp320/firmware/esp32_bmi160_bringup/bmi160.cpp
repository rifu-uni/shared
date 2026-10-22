#include "bmi160.h"

#include <stdio.h>

namespace {
constexpr uint32_t kResetSettleMs = 100;
constexpr uint32_t kAccelStartupMs = 10;   // Datasheet maximum is 3.8 ms in normal mode.
constexpr uint32_t kGyroStartupMs = 100;   // Datasheet maximum is 80 ms in normal mode.

int16_t littleEndian16(const uint8_t* data) {
  return static_cast<int16_t>(static_cast<uint16_t>(data[0]) |
                              (static_cast<uint16_t>(data[1]) << 8));
}
}

Bmi160::Bmi160()
    : wire_(nullptr),
      address_(0),
      chipId_(0),
      ready_(false),
      lastError_("no error") {
  pmuError_[0] = '\0';
}

bool Bmi160::probe(TwoWire& wire, uint8_t address) {
  wire.beginTransmission(address);
  wire.write(Bmi160Reg::CHIP_ID);
  if (wire.endTransmission(false) != 0) {
    return false;
  }
  if (wire.requestFrom(static_cast<uint8_t>(address), static_cast<uint8_t>(1)) != 1) {
    return false;
  }
  return wire.read() == Bmi160Reg::CHIP_ID_BMI160;
}

bool Bmi160::begin(TwoWire& wire, uint8_t address) {
  if (address > 0x7F) {
    lastError_ = "I2C address is out of range";
    return false;
  }

  wire_ = &wire;
  address_ = address;
  chipId_ = 0;
  ready_ = false;
  lastError_ = "no error";

  // Identify the device before resetting it so a wrong chip at this address is never reset.
  if (!readRegister(Bmi160Reg::CHIP_ID, chipId_)) {
    return false;
  }
  if (chipId_ != Bmi160Reg::CHIP_ID_BMI160) {
    lastError_ = "unexpected chip ID";
    return false;
  }

  if (!reset()) {
    return false;
  }

  if (!configure()) {
    return false;
  }

  ready_ = true;
  return true;
}

bool Bmi160::reset() {
  ready_ = false;
  if (!writeRegister(Bmi160Reg::COMMAND, Bmi160Reg::SOFT_RESET)) {
    return false;
  }
  // The chip reloads its registers after a soft reset; give it time before the next access.
  delay(kResetSettleMs);
  return true;
}

bool Bmi160::configure() {
  if (!writeRegister(Bmi160Reg::ACCEL_RANGE, Bmi160Reg::ACCEL_RANGE_2G)) {
    return false;
  }
  if (!verifyRegister(Bmi160Reg::ACCEL_RANGE, Bmi160Reg::ACCEL_RANGE_2G,
                      "accel range read-back mismatch")) {
    return false;
  }

  if (!writeRegister(Bmi160Reg::ACCEL_CONFIG, Bmi160Reg::ACCEL_ODR_100HZ)) {
    return false;
  }
  if (!verifyRegister(Bmi160Reg::ACCEL_CONFIG, Bmi160Reg::ACCEL_ODR_100HZ,
                      "accel ODR read-back mismatch")) {
    return false;
  }

  if (!writeRegister(Bmi160Reg::GYRO_RANGE, Bmi160Reg::GYRO_RANGE_2000DPS)) {
    return false;
  }
  if (!verifyRegister(Bmi160Reg::GYRO_RANGE, Bmi160Reg::GYRO_RANGE_2000DPS,
                      "gyro range read-back mismatch")) {
    return false;
  }

  if (!writeRegister(Bmi160Reg::GYRO_CONFIG, Bmi160Reg::GYRO_ODR_100HZ)) {
    return false;
  }
  if (!verifyRegister(Bmi160Reg::GYRO_CONFIG, Bmi160Reg::GYRO_ODR_100HZ,
                      "gyro ODR read-back mismatch")) {
    return false;
  }

  if (!writeRegister(Bmi160Reg::COMMAND, Bmi160Reg::ACCEL_NORMAL)) {
    return false;
  }
  delay(kAccelStartupMs);

  if (!writeRegister(Bmi160Reg::COMMAND, Bmi160Reg::GYRO_NORMAL)) {
    return false;
  }
  delay(kGyroStartupMs);

  uint8_t pmuStatus = 0;
  if (!readRegister(Bmi160Reg::PMU_STATUS, pmuStatus)) {
    return false;
  }
  // Bits 5:4 are accel PMU status (normal = 0x10); bits 3:2 are gyro (normal = 0x04).
  if ((pmuStatus & 0x3C) != 0x14) {
    snprintf(pmuError_, sizeof(pmuError_), "PMU not normal (PMU_STATUS=0x%02X)", pmuStatus);
    lastError_ = pmuError_;
    return false;
  }

  return true;
}

bool Bmi160::readRaw(Bmi160Raw& raw) {
  if (!ready_) {
    lastError_ = "sensor is not initialized";
    return false;
  }

  // 0x0C..0x17 is contiguous: gyro X/Y/Z then accel X/Y/Z. One burst keeps both
  // sensor values from the same sample instead of two reads 6-16 ms apart.
  uint8_t bytes[12] = {};
  if (!readRegisters(Bmi160Reg::GYRO_DATA_X_LSB, bytes, sizeof(bytes))) {
    return false;
  }

  raw.gyroX = littleEndian16(&bytes[0]);
  raw.gyroY = littleEndian16(&bytes[2]);
  raw.gyroZ = littleEndian16(&bytes[4]);
  raw.accelX = littleEndian16(&bytes[6]);
  raw.accelY = littleEndian16(&bytes[8]);
  raw.accelZ = littleEndian16(&bytes[10]);
  return true;
}

bool Bmi160::readStatus(uint8_t& status) {
  return readRegister(Bmi160Reg::STATUS, status);
}

bool Bmi160::readError(uint8_t& error) {
  return readRegister(Bmi160Reg::ERROR, error);
}

Bmi160Sample Bmi160::convert(const Bmi160Raw& raw) {
  Bmi160Sample sample = {};
  sample.accelG[0] = static_cast<float>(raw.accelX) / Bmi160Reg::ACCEL_LSB_PER_G;
  sample.accelG[1] = static_cast<float>(raw.accelY) / Bmi160Reg::ACCEL_LSB_PER_G;
  sample.accelG[2] = static_cast<float>(raw.accelZ) / Bmi160Reg::ACCEL_LSB_PER_G;
  sample.gyroDps[0] = static_cast<float>(raw.gyroX) / Bmi160Reg::GYRO_LSB_PER_DPS;
  sample.gyroDps[1] = static_cast<float>(raw.gyroY) / Bmi160Reg::GYRO_LSB_PER_DPS;
  sample.gyroDps[2] = static_cast<float>(raw.gyroZ) / Bmi160Reg::GYRO_LSB_PER_DPS;
  return sample;
}

bool Bmi160::writeRegister(uint8_t reg, uint8_t value) {
  if (wire_ == nullptr) {
    lastError_ = "I2C bus is not attached";
    return false;
  }

  wire_->beginTransmission(address_);
  wire_->write(reg);
  wire_->write(value);
  if (wire_->endTransmission() != 0) {
    lastError_ = "I2C write failed";
    return false;
  }
  return true;
}

bool Bmi160::readRegister(uint8_t reg, uint8_t& value) {
  return readRegisters(reg, &value, 1);
}

bool Bmi160::readRegisters(uint8_t reg, uint8_t* data, size_t length) {
  if (wire_ == nullptr) {
    lastError_ = "I2C bus is not attached";
    return false;
  }
  if (data == nullptr || length == 0) {
    lastError_ = "invalid read buffer";
    return false;
  }
  if (length > 255) {
    lastError_ = "register read length exceeds 255 bytes";
    return false;
  }

  wire_->beginTransmission(address_);
  wire_->write(reg);
  if (wire_->endTransmission(false) != 0) {
    lastError_ = "I2C address/register write failed";
    return false;
  }

  const size_t received =
      wire_->requestFrom(static_cast<uint8_t>(address_), static_cast<uint8_t>(length));
  if (received != length) {
    lastError_ = "I2C read returned the wrong byte count";
    return false;
  }

  for (size_t i = 0; i < length; ++i) {
    data[i] = wire_->read();
  }
  lastError_ = "no error";
  return true;
}

bool Bmi160::verifyRegister(uint8_t reg, uint8_t expected, const char* error) {
  uint8_t actual = 0;
  if (!readRegister(reg, actual)) {
    return false;
  }
  if (actual != expected) {
    lastError_ = error;
    return false;
  }
  return true;
}
