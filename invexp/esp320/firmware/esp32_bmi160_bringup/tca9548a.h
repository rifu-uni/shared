#ifndef TCA9548A_H
#define TCA9548A_H

#include <Arduino.h>
#include <Wire.h>

class Tca9548a {
 public:
  Tca9548a();

  bool begin(TwoWire& wire, uint8_t address = 0x70);
  bool isPresent();
  bool select(uint8_t channel);
  bool disableAll();
  bool readSelection(uint8_t& selection);

  // Scans the selected downstream channel. The mux address and every address in
  // ignoredAddresses are never reported. Callers pass the upstream scan result so
  // devices on the ESP32 side are not mistaken for devices behind the mux.
  // The channel stays selected so the caller can talk to the device it just found.
  bool scanChannel(uint8_t channel, uint8_t* addresses, uint8_t capacity,
                   uint8_t& count, const uint8_t* ignoredAddresses,
                   uint8_t ignoredCount);

  const char* lastError() const { return lastError_; }

 private:
  bool writeSelection(uint8_t selection);

  TwoWire* wire_;
  uint8_t address_;
  const char* lastError_;
};

#endif
