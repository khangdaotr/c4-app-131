/* Capture continuously; resample the native input rate to 16 kHz without gaps at chunk boundaries. */
class InterviewPcmCapture extends AudioWorkletProcessor {
  constructor() {
    super()
    this.buffer = new Float32Array(3200)
    this.used = 0
    this.sum = 0
    this.weight = 0
    this.ratio = sampleRate / 16000
    this.running = true
    this.port.onmessage = ({ data }) => {
      if (data.type === "flush") {
        this.running = false
        if (this.weight > 0) this.append(this.sum / this.weight)
        this.emit()
        this.port.postMessage({ type: "flushed" })
      }
    }
  }
  append(value) {
    this.buffer[this.used++] = value
    if (this.used === this.buffer.length) this.emit()
  }
  emit() {
    if (!this.used) return
    const audio = this.buffer.slice(0, this.used)
    this.port.postMessage({ type: "audio", audio }, [audio.buffer])
    this.used = 0
  }
  process(inputs) {
    if (!this.running) return false
    const channels = inputs[0]
    if (!channels?.length) return true
    for (let i = 0; i < channels[0].length; i++) {
      let mono = 0
      for (const channel of channels) mono += channel[i] / channels.length
      let remaining = 1
      while (remaining > 1e-8) {
        const amount = Math.min(remaining, this.ratio - this.weight)
        this.sum += mono * amount
        this.weight += amount
        remaining -= amount
        if (this.weight >= this.ratio - 1e-8) {
          this.append(this.sum / this.weight)
          this.sum = 0
          this.weight = 0
        }
      }
    }
    return true
  }
}
registerProcessor("interview-pcm-capture", InterviewPcmCapture)
