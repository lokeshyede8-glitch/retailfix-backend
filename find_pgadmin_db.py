import os

def find_file(start_dir, target_name):
    print(f"Searching for {target_name} in {start_dir}...")
    for root, dirs, files in os.walk(start_dir):
        # Skip some common large dirs to save time
        dirs[:] = [d for d in dirs if d.lower() not in ["cache", "cached", "npm", "pip", "temp", "tmp", "local history"]]
        for f in files:
            if f.lower() == target_name.lower() or target_name.lower() in f.lower():
                full_path = os.path.join(root, f)
                print(f"Found match: {full_path}")

def main():
    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")
    home = os.path.expanduser("~")
    
    if appdata:
        find_file(appdata, "pgadmin")
    if localappdata:
        find_file(localappdata, "pgadmin")
    find_file(home, ".pgpass")

if __name__ == "__main__":
    main()
