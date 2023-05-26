import sysv_ipc

class Msgq():
    def __init__(self, key_t, flag):
        self.key_t = key_t
        self.flag = flag
        self.MessageQueue = sysv_ipc.MessageQueue(key_t, flag)
    
    def send(self, payload, msg_type):
        self.MessageQueue.send(payload, True, type=msg_type)
    
    def recv(self):
        self.MessageQueue.receive()