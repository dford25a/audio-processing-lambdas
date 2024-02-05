#requires ffmpeg installed
#pip install pydub
from pydub import AudioSegment
import os
import math

myaudio = AudioSegment.from_file('./test25min.m4a')
#myaudio = AudioSegment.from_file(inputdir+"/"+filename, "m4a") 
audio_length = len(myaudio)
print('length of audio: '+str(audio_length))
segment_length = 300000 # 5 min
for i in range(math.ceil(audio_length/segment_length)):
    start_idx = (i-1)*segment_length
    stop_idx = (i)*segment_length
    print('splitting audio at:'+str(start_idx)+' '+str(stop_idx))
    if stop_idx > audio_length:
        stop_idx = audio_length
    chunk_data = myaudio[start_idx:stop_idx]
    chunk_data.export(str(i)+".m4a", format="ipod")