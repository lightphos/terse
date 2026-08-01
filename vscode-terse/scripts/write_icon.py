import base64, os
s = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVQImWNgYAAAAAMAASsJTYQAAAAASUVORK5CYII='
out_dir = os.path.join(os.path.dirname(__file__), '..', 'images')
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, 'icon.png')
with open(out_path, 'wb') as f:
    f.write(base64.b64decode(s))
print('wrote', out_path)
