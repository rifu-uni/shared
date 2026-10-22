#ifndef BMI160_H
#define BMI160_H

#include <Arduino.h>
#include <Wire.h>

namespace Bmi160Reg {
constexpr uint8_t CHIP_ID = 0x00;
constexpr uint8_t ERROR = 0x02;
constexpr uint8_t PMU_STATUS = 0x03;
constexpr uint8_t GYRO_DATA_X_LSB = 0x0C;
constexpr uint8_t ACCEL_DATA_X_LSB = 0x12;
constexpr uint8_t STATUS = 0x1B;
constexpr uint8_t ACCEL_CONFIG = 0x40;
constexpr uint8_t ACCEL_RANGE = 0x41;
constexpr uint8_t GYRO_CONFIG = 0x42;
constexpr uint8_t GYRO_RANGE = 0x43;
constexpr uint8_t COMMAND = 0x7E;

constexpr uint8_t CHIP_ID_BMI160 = 0xD1;
constexpr uint8_t SOFT_RESET = 0xB6;
constexpr uint8_t ACCEL_NORMAL = 0x11;
constexpr uint8_t GYRO_NORMAL = 0x15;
constexpr uint8_t ACCEL_RANGE_2G = 0x03;
constexpr uint8_t ACCEL_ODR_100HZ = 0x28;
constexpr uint8_t GYRO_RANGE_2000DPS = 0x00;
constexpr uint8_t GYRO_ODR_100HZ = 0x28;

constexpr float ACCEL_LSB_PER_G = 16384.0f;
constexpr float GYRO_LSB_PER_DPS = 16.4f;
}

struct Bmi160Raw {
  int16_t accelX;
  int16_t accelY;
  int16_t accelZ;
  int16_t gyroX;
  int16_t gyroY;
  int16_t gyroZ;
};

struct Bmi160Sample {
  float accelG[3];
  float gyroDps[3];
};

class Bmi160 {
 public:
  Bmi160();

  // True only if the device ACKs and returns the BMI160 chip ID. Does not configure it.
  static bool probe(TwoWire& wire, uint8_t address);

  bool begin(TwoWire& wire, uint8_t address);
  bool reset();
  bool configure();
  bool readRaw(Bmi160Raw& raw);
  bool readStatus(uint8_t& status);
  bool readError(uint8_t& error);
  static Bmi160Sample convert(const Bmi160Raw& raw);

  uint8_t address() const { return address_; }
  uint8_t chipId() const { return chipId_; }
  bool isReady() const { return ready_; }
  const char* lastError() const { return lastError_; }

 private:
  bool writeRegister(uint8_t reg, uint8_t value);
  bool readRegister(uint8_t reg, uint8_t& value);
  bool readRegisters(uint8_t reg, uint8_t* data, size_t length);
  bool verifyRegister(uint8_t reg, uint8_t expected, const char* error);

  TwoWire* wire_;
  uint8_t address_;
  uint8_t chipId_;
  bool ready_;
  const char* lastError_;
  char pmuError_[48];
};

#endif
