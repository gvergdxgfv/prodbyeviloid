import os
import subprocess

def test_cinematic_filters():
    # Find a test video clip to apply effects to
    vid_in = "test_ig_video.mp4"
    if not os.path.exists(vid_in):
        # Fallback to any clips
        import glob
        clips = glob.glob("clips/**/*.mp4", recursive=True)
        if clips:
            vid_in = clips[0]
        else:
            print("No video found to test.")
            return

    out_path = "output/test_cinematic_effects.mp4"

    # Simulated beat drops at 1.0s and 3.0s
    drop_times = [1.0, 3.0]
    
    # Construct Zoompan expression for beat drops
    # zoom = 1.05 and easing to 1.0 over 0.25s
    z_exprs = []
    for dt in drop_times:
        # 1.05 - (t - dt) * 0.2
        expr = f"if(between(in_time,{dt},{dt+0.25}), 1.05-(in_time-{dt})*0.2, 1)"
        z_exprs.append(expr)
        
    # Chain them or just use the first match
    if z_exprs:
        # nested ifs
        # if(cond1, val1, if(cond2, val2, 1))
        z_full = "1"
        for expr in reversed(z_exprs):
            # replacing the ending ', 1)' with the growing next condition
            z_full = expr.replace(", 1)", f", {z_full})")
    else:
        z_full = "1"
        
    zoompan_filter = f"zoompan=z='{z_full}':d=1:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s=1080x1920:fps=30"
    
    # Cinematic color filter: contrast up, saturation up, slight vignette, noise
    cinematic_filter = "eq=contrast=1.1:saturation=1.2:gamma=0.95"
    vignette_filter = "vignette=PI/4"
    noise_filter = "noise=alls=4:allf=t+u"
    
    # Combo
    combo_filter = f"[0:v]{zoompan_filter},{cinematic_filter},{vignette_filter},{noise_filter}[outv]"

    cmd = [
        "ffmpeg", "-y",
        "-i", vid_in,
        "-filter_complex", combo_filter,
        "-map", "[outv]",
        "-map", "0:a?",
        "-t", "5",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        out_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("Success!")
    except subprocess.CalledProcessError as e:
        print("FFmpeg Failed!")
        print(e.stderr)

if __name__ == "__main__":
    test_cinematic_filters()
