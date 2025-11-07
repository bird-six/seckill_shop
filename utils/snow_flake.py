import threading
import time

class Snowflake:
    """
    雪花算法实现：生成64位分布式唯一ID
    结构：1位符号位 + 41位时间戳 + 5位数据中心ID + 5位机器ID + 12位序列号
    """
    # 单例实例
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """确保类只有一个实例"""
        with cls._lock:
            if not cls._instance:
                cls._instance = super(Snowflake, cls).__new__(cls)
        return cls._instance

    def __init__(self, data_center_id: int = 1, worker_id: int = 1, epoch: int = 1288834974657):
        """
        初始化雪花算法生成器
        :param data_center_id: 数据中心ID (0-31，5位)
        :param worker_id: 机器ID (0-31，5位)
        :param epoch: 起始时间戳(毫秒)，默认Twitter的起始时间(2010-11-04 01:42:54 UTC)
        """
        # 防止重复初始化
        if hasattr(self, 'initialized'):
            return

        # 校验数据中心ID和机器ID范围
        if data_center_id < 0 or data_center_id > 31:
            raise ValueError("数据中心ID必须在0-31之间")
        if worker_id < 0 or worker_id > 31:
            raise ValueError("机器ID必须在0-31之间")

        self.data_center_id = data_center_id
        self.worker_id = worker_id
        self.epoch = epoch  # 起始时间戳

        # 位偏移量定义
        self.timestamp_bits = 41
        self.data_center_bits = 5
        self.worker_bits = 5
        self.sequence_bits = 12

        # 最大取值计算
        self.max_data_center_id = (1 << self.data_center_bits) - 1  # 31
        self.max_worker_id = (1 << self.worker_bits) - 1  # 31
        self.max_sequence = (1 << self.sequence_bits) - 1  # 4095

        # 位偏移量
        self.worker_shift = self.sequence_bits  # 12
        self.data_center_shift = self.sequence_bits + self.worker_bits  # 17
        self.timestamp_shift = self.data_center_shift + self.data_center_bits  # 22

        # 状态变量
        self.last_timestamp = -1  # 上一次生成ID的时间戳
        self.sequence = 0  # 当前毫秒内的序列号
        self.lock = threading.Lock()  # 线程锁保证并发安全
        self.initialized = True

    def _get_current_timestamp(self) -> int:
        """获取当前毫秒级时间戳"""
        return int(time.time() * 1000)

    def generate_id(self) -> int:
        """生成唯一ID"""
        with self.lock:  # 加锁保证线程安全
            current_timestamp = self._get_current_timestamp()

            # 处理时钟回拨（当前时间小于上一次生成ID的时间）
            if current_timestamp < self.last_timestamp:
                raise RuntimeError(
                    f"时钟回拨异常：当前时间戳({current_timestamp}) < 上一次时间戳({self.last_timestamp})"
                )

            # 同一毫秒内，序列号自增
            if current_timestamp == self.last_timestamp:
                self.sequence += 1
                # 序列号超出最大值，等待到下一毫秒
                if self.sequence > self.max_sequence:
                    # 循环等待下一毫秒
                    while current_timestamp <= self.last_timestamp:
                        current_timestamp = self._get_current_timestamp()
                    self.sequence = 0  # 重置序列号
            else:
                # 不同毫秒，重置序列号
                self.sequence = 0

            # 更新上一次时间戳
            self.last_timestamp = current_timestamp

            # 组合ID各部分（位运算）
            timestamp_part = (current_timestamp - self.epoch) << self.timestamp_shift
            data_center_part = self.data_center_id << self.data_center_shift
            worker_part = self.worker_id << self.worker_shift
            sequence_part = self.sequence

            return timestamp_part | data_center_part | worker_part | sequence_part

    @classmethod
    def generate_id_static(cls) -> int:
        """静态方法，用于模型默认值"""
        # 获取或创建单例实例
        if not cls._instance:
            cls._instance = cls()
        return cls._instance.generate_id()

