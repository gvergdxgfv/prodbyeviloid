import os
import sys
import time

# ANSI Escape Sequences for Colors
class Colors:
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"

BANNER = r"""
  ______      _______ _      ____ _____ _____  
 |  ____|    |_   _| |    / __ \_   _|  __ \ 
 | |__ __   __ | | | |   | |  | || | | |  | |
 |  __|\ \ / / | | | |   | |  | || | | |  | |
 | |____\ V / _| |_| |___| |__| || |_| |__| |
 |______|\_/ |_____|______\____/_____|_____/ 
                                             
              [ BEAT-TO-CONTENT AUTOMATION PIPELINE ]
"""

def print_banner():
    """Prints the stylized ASCII banner with a gradient-like effect."""
    lines = BANNER.split("\n")
    colors = [Colors.CYAN, Colors.BLUE, Colors.MAGENTA]
    
    print(Colors.BOLD, end="")
    for i, line in enumerate(lines):
        color = colors[i % len(colors)]
        print(f"{color}{line}")
    print(Colors.END)

def print_intro():
    """Prints the banner and a quick loading animation."""
    # Ensure ANSI colors work on Windows
    if os.name == 'nt':
        os.system('color')
        
    print_banner()
    
    # Subtle loading indicator
    msgs = ["Initializing AI models...", "Scanning beats folder...", "Connecting to Meta API...", "Ready 🚀"]
    for msg in msgs:
        sys.stdout.write(f"\r{Colors.YELLOW}⚡ {msg}{Colors.END}")
        sys.stdout.flush()
        time.sleep(0.3)
    print("\n" + "─" * 60 + "\n")

def get_help_header():
    """Returns the banner as a string for use in argparse epilog/description."""
    # Strip some detail for help text to stay clean
    return f"{Colors.CYAN}{BANNER}{Colors.END}"
