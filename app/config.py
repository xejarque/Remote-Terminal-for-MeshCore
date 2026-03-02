import logging
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MESHCORE_")

    serial_port: str = ""  # Empty string triggers auto-detection
    serial_baudrate: int = 115200
    tcp_host: str = ""
    tcp_port: int = 4000
    ble_address: str = ""
    ble_pin: str = ""
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_path: str = "data/meshcore.db"

    @model_validator(mode="after")
    def validate_transport_exclusivity(self) -> "Settings":
        transports_set = sum(
            [
                bool(self.serial_port),
                bool(self.tcp_host),
                bool(self.ble_address),
            ]
        )
        if transports_set > 1:
            raise ValueError(
                "Only one transport may be configured at a time. "
                "Set exactly one of MESHCORE_SERIAL_PORT, MESHCORE_TCP_HOST, or MESHCORE_BLE_ADDRESS."
            )
        if self.ble_address and not self.ble_pin:
            raise ValueError("MESHCORE_BLE_PIN is required when MESHCORE_BLE_ADDRESS is set.")
        return self

    @property
    def loopback_eligible(self) -> bool:
        """True when no explicit transport env var is set."""
        return not self.serial_port and not self.tcp_host and not self.ble_address

    @property
    def connection_type(self) -> Literal["serial", "tcp", "ble"]:
        if self.tcp_host:
            return "tcp"
        if self.ble_address:
            return "ble"
        return "serial"


settings = Settings()


def setup_logging() -> None:
    """Configure logging for the application."""
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
