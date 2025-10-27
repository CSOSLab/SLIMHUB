import numpy as np
import struct
from dataclasses import dataclass

MODEL_UPDATE_CMD_START = 1
MODEL_UPDATE_CMD_DATA = 2
MODEL_UPDATE_CMD_END = 3
MODEL_UPDATE_CMD_REMOVE = 4
MODEL_UPDATE_CMD_FAIL = 11

FEATURE_COLLECTION_CMD_START = 5
FEATURE_COLLECTION_CMD_DATA = 6
FEATURE_COLLECTION_CMD_FINISH = 7
FEATURE_COLLECTION_CMD_END = 8

# Base packet class with only the cmd field
@dataclass
class ModelPacket:
    cmd: int  # uint8_t

    def pack(self) -> bytes:
        """Pack the cmd field into a bytes object."""
        packet_format = '<B'
        return struct.pack(packet_format, self.cmd)

    @classmethod
    def unpack(cls, packet_data: bytes) -> 'ModelPacket':
        """Unpack bytes into a ModelPacket object."""
        cmd, = struct.unpack('<B', packet_data[:1])
        return cls(cmd=cmd)


# Acknowledgment packet with cmd and seq fields
@dataclass
class ModelAckPacket(ModelPacket):
    seq: int  # uint16_t

    def pack(self) -> bytes:
        """Pack the cmd and seq fields into a bytes object."""
        packet_format = '<B H'
        return struct.pack(packet_format, self.cmd, self.seq)

    @classmethod
    def unpack(cls, packet_data: bytes) -> 'ModelAckPacket':
        """Unpack bytes into a ModelAckPacket object."""
        cmd, seq = struct.unpack('<B H', packet_data[:3])
        return cls(cmd=cmd, seq=seq)


# Data packet with cmd, seq, and data fields
@dataclass
class ModelDataPacket(ModelPacket):
    seq: int  # uint16_t
    data: bytes  # 128-byte fixed data field

    def pack(self) -> bytes:
        """Pack the cmd, seq, and data fields into a bytes object."""
        packet_format = '<B H 128s'
        padded_data = self.data.ljust(128, b'\xFF')  # Ensure data is 128 bytes
        return struct.pack(packet_format, self.cmd, self.seq, padded_data)

    @classmethod
    def unpack(cls, packet_data: bytes) -> 'ModelDataPacket':
        """Unpack bytes into a ModelDataPacket object."""
        cmd, seq, data = struct.unpack('<B H 128s', packet_data[:131])
        return cls(cmd=cmd, seq=seq, data=data)
    
@dataclass
class SoundFeaturePacket:
    cmd: int       # uint8_t
    seq: int       # uint16_t
    data: np.ndarray  # float16[48] 

    @classmethod
    def unpack(cls, packet_data: bytes) -> 'SoundFeaturePacket':
        """Unpack bytes into a Packet object."""
        # 먼저 cmd (1바이트)와 seq (2바이트)를 언패킹
        cmd, seq = struct.unpack('<B H', packet_data[:3])

        # 나머지 데이터 부분 (48 * 2 = 96바이트)을 float16로 변환
        data = np.frombuffer(packet_data[3:], dtype=np.float16)

        return cls(cmd=cmd, seq=seq, data=data)
    
FILE_TRANSFER_CMD_START = 1
FILE_TRANSFER_CMD_DATA = 2
FILE_TRANSFER_CMD_END = 3
FILE_TRANSFER_CMD_REMOVE = 4
FILE_TRANSFER_CMD_FAIL = 11

# Base packet class with only the cmd field
@dataclass
class FilePacket:
    cmd: int  # uint8_t

    def pack(self) -> bytes:
        """Pack the cmd field into a bytes object."""
        packet_format = '<B'
        return struct.pack(packet_format, self.cmd)

    @classmethod
    def unpack(cls, packet_data: bytes) -> 'FilePacket':
        """Unpack bytes into a FilePacket object."""
        cmd, = struct.unpack('<B', packet_data[:1])
        return cls(cmd=cmd)


# Acknowledgment packet with cmd and seq fields
@dataclass
class FileAckPacket(FilePacket):
    seq: int  # uint16_t

    def pack(self) -> bytes:
        """Pack the cmd and seq fields into a bytes object."""
        packet_format = '<B H'
        return struct.pack(packet_format, self.cmd, self.seq)

    @classmethod
    def unpack(cls, packet_data: bytes) -> 'FileAckPacket':
        """Unpack bytes into a FileAckPacket object."""
        cmd, seq = struct.unpack('<B H', packet_data[:3])
        return cls(cmd=cmd, seq=seq)


# Data packet with cmd, seq, and data fields
@dataclass
class FileDataPacket(FilePacket):
    seq: int  # uint16_t
    size: int
    data: bytes  # 128-byte fixed data field

    def pack(self) -> bytes:
        """Pack the cmd, seq, and data fields into a bytes object."""
        packet_format = '<B H H 128s'
        padded_data = self.data.ljust(128, b'\xFF')  # Ensure data is 128 bytes
        return struct.pack(packet_format, self.cmd, self.seq, self.size, padded_data)

    @classmethod
    def unpack(cls, packet_data: bytes) -> 'FileDataPacket':
        """Unpack bytes into a FileDataPacket object."""
        cmd, seq, size, data = struct.unpack('<B H H 128s', packet_data[:133])
        return cls(cmd=cmd, seq=seq, size=size, data=data)