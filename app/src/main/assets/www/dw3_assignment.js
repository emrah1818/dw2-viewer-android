/** Explicit manual selection must replace an automatic multi-motion action. */
export function chooseMotion(assignment, motion) {
  return { ...assignment, selection: 'motion', motion: motion.id,
    loop: motion.end === 'loop' || motion.end === 'idle' };
}

export function motionEndText(motion) {
  if (motion.end === 'loop') return `DW3-Schleife ab Bild ${motion.loop_frame}`;
  if (motion.end === 'idle') return 'danach Standby-Schleife';
  return 'letztes Bild halten';
}
