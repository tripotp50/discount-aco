import os

DATA_DIR = "/var/data"
os.makedirs(DATA_DIR, exist_ok=True)

with open(os.path.join(DATA_DIR, "test.txt"), "w") as f:
    f.write("hello from Render disk")
