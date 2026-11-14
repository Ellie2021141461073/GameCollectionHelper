'use client';
import { useEffect, useState } from 'react';

export default function CardThumb({ src, name }: { src?: string; name: string }) {
  const [failed, setFailed] = useState(false);

  useEffect(() => setFailed(false), [src]);

  return <span className="card-thumb">
    {src && !failed
      ? <img src={src} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />
      : <span>{name.slice(0, 1)}</span>}
  </span>;
}
