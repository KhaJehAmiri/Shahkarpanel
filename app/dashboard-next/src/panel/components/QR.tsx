import { FC, useEffect, useState } from "react";
import QRCode from "qrcode";

export const QR: FC<{ value: string; size?: number }> = ({ value, size = 180 }) => {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let alive = true;
    QRCode.toDataURL(value, { width: size, margin: 1, errorCorrectionLevel: "M" })
      .then((url) => alive && setSrc(url))
      .catch(() => alive && setSrc(""));
    return () => { alive = false; };
  }, [value, size]);
  if (!src) return <div className="sk-skel" style={{ width: size, height: size, borderRadius: 10 }} />;
  return <img src={src} width={size} height={size} alt="QR" style={{ borderRadius: 10, background: "#fff", padding: 6 }} />;
};
