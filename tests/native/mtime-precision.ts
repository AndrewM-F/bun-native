/** Match the native wire contract: whole milliseconds rounded toward -infinity. */
export function wholeUnixMilliseconds(nanoseconds: bigint): bigint {
  const unit = 1_000_000n
  const quotient = nanoseconds / unit
  return nanoseconds < 0n && nanoseconds % unit !== 0n ? quotient - 1n : quotient
}
