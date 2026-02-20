import os
import subprocess

def test_visualizer():
    audio_path = "beats/looperman-l-5360566-0410578-electric-guitar-loop-100bpm.mp4" # We need an actual audio file from beats/
    # Let's find an actual beat
    beats_dir = "beats"
    beats = [f for f in os.listdir(beats_dir) if f.endswith(".mp3") or f.endswith(".wav")]
    if not beats:
        print("No beats found in beats/")
        return
        
    audio_path = os.path.join(beats_dir, beats[0])
    out_path = "output/test_ffmpeg_viz.mp4"
    
    font_path = "/Windows/Fonts/ariblk.ttf"
    if not os.path.exists("C:/Windows/Fonts/ariblk.ttf"):
        font_path = "/Windows/Fonts/arial.ttf"
        
    theme_color = "0x00FFCC"
    beat_name = "Test Beat"
    producer_tag = "Prod. Eviloid"

    # Filtergraph
    # 1. Black background 1080x1920
    # 2. showwaves across 960x400
    # 3. overlay it
    # 4. drawtext for title and tag
    filtergraph = (
        f"color=c=black:s=1080x1920:r=30[bg];"
        f"[0:a]showwaves=s=960x400:mode=cline:colors={theme_color}:scale=sqrt[wave];"
        f"[bg][wave]overlay=(W-w)/2:(H-h)/2+100[v1];"
        f"[v1]drawtext=fontfile='{font_path}':text='{beat_name}':fontcolor=white:fontsize=50:x=(w-text_w)/2:y=(h-text_h)/2-150[v2];"
        f"[v2]drawtext=fontfile='{font_path}':text='{producer_tag}':fontcolor=white:fontsize=40:x=(w-text_w)/2:y=h-150[outv]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", "0", "-t", "5",
        "-i", audio_path,
        "-filter_complex", filtergraph,
        "-map", "[outv]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        out_path
    ]
    
    print("Running:", " ".join(cmd))
    subprocess.run(cmd)

if __name__ == "__main__":
    test_visualizer()
