module.exports = {
  nodes: [
    require('./dist/nodes/Yak-ChatterboxTTS/ChatterboxTTS.node').YakChatterboxTTS,
    require('./dist/nodes/Yak-ComfyUI/ComfyUI.node').YakComfyUI,
    require('./dist/nodes/Yak-FFMPEG/FFMPEG.node').YakFFMPEG,
    require('./dist/nodes/Yak-MuseTalk/MuseTalk.node').YakMuseTalk,
    require('./dist/nodes/Yak-VocalRemover/VocalRemover.node').YakVocalRemover,
    require('./dist/nodes/Yak-WhisperSTT/WhisperSTT.node').YakWhisperSTT,
  ],
  credentials: [],
};