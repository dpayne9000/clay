import sys

# Reads a newline-separated file listing (listWorkspace's output format) on
# stdin and prints only the paths that are plausibly a Dockerfile: the
# basename is exactly "Dockerfile" (any case) or ends in ".dockerfile".
# Keeps the discovery step from trying to serveFileReads the whole repo
# listing, which would blow past serveFileReads' maxFiles cap on unrelated
# files before it ever reached an actual Dockerfile.

for line in sys.stdin.read().splitlines():
    path = line.strip()
    if not path:
        continue
    basename = path.rsplit("/", 1)[-1]
    if basename.lower() == "dockerfile" or basename.lower().endswith(".dockerfile"):
        print(path)
