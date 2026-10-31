import logoMark from '../assets/logo-mark.png'
import logoSphere from '../assets/logo-sphere.png'
import './LogoMark.css'

/**
 * The full logo mark. logo-mark.png has its sphere cut out (the intro page
 * animates it separately), so the sphere is laid back on here. Size it with
 * `width` on the given class; the sphere scales along.
 */
export function LogoMark({ className = '' }: { className?: string }) {
  return (
    <span className={`logo-mark ${className}`}>
      <img src={logoMark} alt="" width={360} height={228} />
      <img className="logo-mark__sphere" src={logoSphere} alt="" width={41} height={41} />
    </span>
  )
}
