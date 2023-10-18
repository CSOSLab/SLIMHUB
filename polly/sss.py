
import vlc
import time
media_player = vlc.MediaPlayer()
media_player.set_media(vlc.Media("/home/rtlab/Desktop/polly/1.mp3"))
            
# 볼륨 조정하기
media_player.audio_set_volume(100)
time.sleep(1)

media_player.play()
time.sleep(3)
