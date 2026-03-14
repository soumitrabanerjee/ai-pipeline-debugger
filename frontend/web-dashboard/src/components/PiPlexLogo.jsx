export default function PiPlexLogo({ height = 36 }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 152 40"
      height={height}
      style={{ width: "auto", display: "block" }}
      aria-label="PiPlex"
    >
      <defs>
        <linearGradient id="piplex-grad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#6366f1" />
          <stop offset="100%" stopColor="#a78bfa" />
        </linearGradient>
      </defs>

      {/* Hexagon icon */}
      <path d="M15,3 L25,3 L31,13 L25,23 L15,23 L9,13 Z" fill="url(#piplex-grad)" />

      {/* Pipeline flow arrows */}
      <path d="M13,10 L17,13 L13,16"
        fill="none" stroke="white" strokeWidth="2.2"
        strokeLinecap="round" strokeLinejoin="round" />
      <path d="M18,10 L22,13 L18,16"
        fill="none" stroke="white" strokeWidth="2.2"
        strokeLinecap="round" strokeLinejoin="round" opacity="0.55" />

      {/* Wordmark */}
      <text x="40" y="28"
        fontFamily="-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
        fontWeight="800" fontSize="22" fill="white">Pi</text>
      <text x="65" y="28"
        fontFamily="-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
        fontWeight="800" fontSize="22" fill="#818cf8">Plex</text>
    </svg>
  );
}
