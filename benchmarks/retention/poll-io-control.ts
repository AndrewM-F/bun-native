/** Sequential loopback round trips exercise event-loop I/O, not native UI presentation. */
import { writeFileSync } from 'node:fs'
import { createConnection, createServer } from 'node:net'

const output = process.argv[2]
if (!output) throw new Error('Output path required')
const warmup = 1_000
const measured = 50_000
const expected = warmup + measured
const server = createServer((socket) => {
  socket.setNoDelay(true)
  socket.on('data', (data) => socket.write(data))
  socket.on('end', () => socket.end())
})
await new Promise<void>((resolve, reject) => {
  server.once('error', reject)
  server.listen(0, '127.0.0.1', resolve)
})
const address = server.address()
if (!address || typeof address === 'string') throw new Error('No loopback address')
const client = createConnection({ host: '127.0.0.1', port: address.port })
client.setNoDelay(true)
let index = 0
let pending = Buffer.alloc(0)
let started = 0
let finished = 0
function send() {
  const payload = Buffer.allocUnsafe(8)
  payload.writeBigUInt64LE(BigInt(index))
  client.write(payload)
}
const timeout = setTimeout(() => {
  throw new Error('Loopback control timed out')
}, 90_000)
await new Promise<void>((resolve, reject) => {
  client.once('error', reject)
  client.once('connect', () => send())
  client.on('data', (chunk) => {
    if (typeof chunk === 'string') return reject(new Error('Unexpected text-mode socket data'))
    pending = Buffer.concat([pending, chunk])
    while (pending.length >= 8) {
      const received = pending.readBigUInt64LE()
      pending = pending.subarray(8)
      if (received !== BigInt(index)) return reject(new Error('Loopback payload or order mismatch'))
      index++
      if (index === warmup) started = performance.now()
      if (index === expected) {
        finished = performance.now()
        client.end()
        return
      }
      send()
    }
  })
  client.once('close', () => resolve())
})
clearTimeout(timeout)
await new Promise<void>((resolve, reject) =>
  server.close((error) => (error ? reject(error) : resolve()))
)
if (index !== expected || pending.length !== 0 || !(finished > started))
  throw new Error('Incomplete loopback control')
writeFileSync(
  output,
  JSON.stringify(
    {
      revision: Bun.revision,
      executable: process.execPath,
      warmup,
      measured,
      completed: index,
      elapsedMs: finished - started,
      payloadBytes: 8,
      transport: 'tcp-loopback',
      cleanup: 'client closed and server closed',
    },
    null,
    2
  ) + '\n',
  { flag: 'wx' }
)
