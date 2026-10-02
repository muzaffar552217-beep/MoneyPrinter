import os
import subprocess
from gTTS import gTTS

# 1. Voiceover create karo
text = "Jo muskuraha hai use dard ne paala hoga, jo chal raha hai uske paanv mein chhaala hoga."
tts = gTTS(text=text, lang='hi')
tts.save("voice.mp3")

# 2. Vertical Video Render karo
cmd = "ffmpeg -y -f lavfi -i color=c=0x0f0f1d:s=1080x1920:r=24 -i voice.mp3 -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac -b:a 192k -shortest final_short.mp4"
subprocess.run(cmd, shell=True, check=True)

print("SUCCESS: Video Created!")
