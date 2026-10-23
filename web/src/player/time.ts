/** m:ss, for the transport's readout and the slider's spoken value. A
 * duration that is not known yet (NaN, before the metadata loads) reads 0:00
 * rather than "NaN:NaN". */
export function clock(seconds: number): string {
  const whole = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
