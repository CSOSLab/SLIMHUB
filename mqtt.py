import paho.mqtt.client as mqtt

class Mqtt():
    def __init__(self, ip, port, id, passwd, sh_id, client_id=None):
        self.ip = ip
        self.port = port
        self.id = id
        self.passwd = passwd
        self.client = mqtt.Client(client_id)

        self.sh_id = sh_id

    def connect(self):
        self.client.username_pw_set(username=self.id, password=self.passwd)
        self.client.connect(self.ip, self.port)

    def publish(self, topic, message):
        self.client.publish(topic, message)

    def disconnect(self):
        self.client.disconnect()