I co-host a podcast. My name is Hunter. My co-host's name is Daniel.
We recently recorded an episode.
Our audio was recorded on seperate channels.
@hunter.mp3 is my audio. @daniel.mp3 is daniel's audio.

I also uploaded these files to a public bucket

- https://storage.googleapis.com/ghost-feed-shorts/tmp/hunter.mp3
- https://storage.googleapis.com/ghost-feed-shorts/tmp/daniel.mp3

I would like to create a transcript for the episode using ElevenLabs API.

I have stored an ElevenLabs API key, `ELEVENLABS_API_KEY`, in @.env

I want to leverage their `Multichannel speech-to-text` support. They have documentation here, https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/batch/multichannel-transcription, but I also downloaded the documentation to @multichannel-transcription.md

I would like the transcript in at least two formats. For one I want the most detailed version (which I think is just what their API returns as a JSON response) I need this version, because I am going to use a LLM to determine some edit points and they need to be exact.

Then I would also like a very human readable version of the podcast. The docs reference `Creating conversation transcripts`. I think this is what I want for that.

Use python to interact with the API. `uv` is available to install anything. don't use `pip`.
