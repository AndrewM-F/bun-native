/** Bounded polling evidence; it does not change the speech acceptance window. */
export class PhraseTiming {
  #samples: Array<{
    index: number
    startMs: number
    endMs: number
    hostPidStart: number
    hostPidEnd: number
  }> = []
  #omitted = 0

  constructor(private readonly limit = 256) {}

  add(
    index: number,
    startMs: number,
    endMs: number,
    hostPidStart: number,
    hostPidEnd: number
  ): void {
    if (this.#samples.length >= this.limit) {
      this.#omitted += 1
      return
    }
    this.#samples.push({ index, startMs, endMs, hostPidStart, hostPidEnd })
  }

  snapshot() {
    return { samples: this.#samples.map((sample) => ({ ...sample })), omitted: this.#omitted }
  }
}
