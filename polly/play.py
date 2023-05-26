import os
import time
import paho.mqtt.client as mqtt
class Mqtt():
    def __init__(self, ip,port,id,passwd):
        self.ip = ip
        self.port = port
        self.id=id
        self.passwd=passwd
        # 새로운 클라이언트 생성
        self.client = mqtt.Client("Foot_Pressure")
        # 콜백 함수 설정 on_connect(브로커에 접속), on_disconnect(브로커에 접속중료), on_subscribe(topic 구독),
        # on_message(발행된 메세지가 들어왔을 때)
        
    def connect(self):
        self.client.username_pw_set(username=self.id,password=self.passwd)
        self.client.connect(self.ip, self.port)
        print("connect the mqtt")
    
    def publish(self,topic,message):
        self.client.publish(topic,message)
    
    def subscribe(self, topic):
        def on_message(client, userdata, msg):                
            print(f"Received `{msg.payload.decode()}` from `{msg.topic}` topic")
            # 읽어드린 미디어파일을 media_player 객체에 세팅하기(재생목록)
            os.system("mplayer /home/rtlab/Desktop/polly/"+str(msg.payload.decode()[12])+".mp3")
        self.client.subscribe(topic)
        self.client.on_message = on_message
        self.client.loop_forever()
        
    def disconnect(self):
        self.client.disconnect()
mqtt=Mqtt("155.230.186.105",1883,"rtlab_SUB","RTLab123!")
mqtt.connect()
# mqtt.publish("CSOS/AB000013/000001E8/FOOT_PRESSURE/","1")
mqtt.subscribe("CSOS/AB000013/000001E8/FOOT_PRESSURE/")
