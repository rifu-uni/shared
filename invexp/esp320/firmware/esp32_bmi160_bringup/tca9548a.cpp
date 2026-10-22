#include "tca9548a.h"

namespace {
constexpr uint8_t kFirstI2cAddress = 0x08;
constexpr uint8_t kLastI2cAddress = 0x77;

bool isIgnoredAddress(uint8_t candidate, const uint8_t* ignoredAddresses,
                      uint8_t ignoredCount) {
  if (ignoredAddresses == nullptr) {
    return false;
  }

  for (uint8_t i = 0; i < ignoredCount; ++i) {
    if (ignoredAddresses[i] == candidate) {
      return true;
    }
  }

  return false;
}
}

Tca9548a::Tca9548a()
    : wire_(nullptr), address_(0x70), lastError_("no error") {}

bool Tca9548a::begin(TwoWire& wire, uint8_t address) {
  if (address > 0x7F) {
    lastError_ = "I2C address is out of range";
    return false;
  }

  wire_ = &wire;
  address_ = address;
  lastError_ = "no error";

  uint8_t selection = 0;
  if (!readSelection(selection)) {
    return false;
  }

  return true;
}

bool Tca9548a::isPresent() {
  uint8_t selection = 0;
  return readSelection(selection);
}

bool Tca9548a::select(uint8_t channel) {
  if (channel > 7) {
    lastError_ = "mux channel is out of range";
    return false;
  }

  const uint8_t requested = static_cast<uint8_t>(1u << channel);
  if (!writeSelection(requested)) {
    return false;
  }

  uint8_t actual = 0;
  if (!readSelection(actual)) {
    return false;
  }
  if (actual != requested) {
    lastError_ = "mux channel read-back mismatch";
    return false;
  }

  return true;
}

bool Tca9548a::disableAll() {
  if (!writeSelection(0)) {
    return false;
  }

  uint8_t actual = 0;
  if (!readSelection(actual)) {
    return false;
  }
  if (actual != 0) {
    lastError_ = "mux disable read-back mismatch";
    return false;
  }

  return true;
}

bool Tca9548a::readSelection(uint8_t& selection) {
  if (wire_ == nullptr) {
    lastError_ = "I2C bus is not attached";
    return false;
  }

  if (wire_->requestFrom(static_cast<uint8_t>(address_), static_cast<uint8_t>(1)) != 1) {
    lastError_ = "mux control register read failed";
    return false;
  }

  selection = wire_->read();
  lastError_ = "no error";
  return true;
}

bool Tca9548a::scanChannel(uint8_t channel, uint8_t* addresses, uint8_t capacity,
                           uint8_t& count, const uint8_t* ignoredAddresses,
                           uint8_t ignoredCount) {
  count = 0;

  if (addresses == nullptr || capacity == 0) {
    lastError_ = "invalid scan buffer";
    return false;
  }

  if (!select(channel)) {
    return false;
  }

  for (uint8_t candidate = kFirstI2cAddress; candidate <= kLastI2cAddress; ++candidate) {
    // The mux itself still ACKs at its upstream address while a channel is selected.
    // Upstream devices also ACK, so skip everything the upstream scan found.
    if (candidate == address_ ||
        isIgnoredAddress(candidate, ignoredAddresses, ignoredCount)) {
      continue;
    }

    wire_->beginTransmission(candidate);
    if (wire_->endTransmission() != 0) {
      continue;
    }

    if (count < capacity) {
      addresses[count] = candidate;
      ++count;
    }
  }

  return true;
}

bool Tca9548a::writeSelection(uint8_t selection) {
  if (wire_ == nullptr) {
    lastError_ = "I2C bus is not attached";
    return false;
  }

  wire_->beginTransmission(address_);
  wire_->write(selection);
  if (wire_->endTransmission() != 0) {
    lastError_ = "mux control register write failed";
    return false;
  }

  return true;
}
