import audio_metadata

def print_meta(location):
    if not os.path.exists(location):
        print("File ", location, "doesn't exist")
    else:
        metadata = audio_metadata.load(location)
        print(metadata)


if __name__ == '__main__':
    metadata = audio_metadata.load('05 - Heart of Hearts.flac')