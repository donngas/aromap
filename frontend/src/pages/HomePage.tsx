import { useRef } from 'react'
import diffuserImage from '../assets/home-diffuser.png'
import spaceImage from '../assets/home-space.png'
import { LogoMark } from '../components/LogoMark.tsx'
import { useWanderingRibbons } from '../components/useWanderingRibbons.ts'
import './HomePage.css'

interface HomePageProps {
  /** Opens the service introduction (the scroll-driven page). */
  onIntro: () => void
  /** Continues into the app, as the introduction's start button used to. */
  onStart: () => void
}

/** First screen (design: designs/랜딩페이지v2.png). */
export function HomePage({ onIntro, onStart }: HomePageProps) {
  return (
    <div className="home">
      <header className="home__brand">
        <h1 className="home__lockup">
          <LogoMark className="home__mark" />
          <span className="home__wordmark">AROMAP</span>
        </h1>
        <p className="home__tagline">보이지 않는 향을, 공간 위에.</p>
      </header>

      <div className="home__stage" aria-hidden="true">
        <Scene />
      </div>

      <div className="home__actions">
        <button type="button" className="home__button home__button--outline" onClick={onIntro}>
          서비스 소개
          <OpenIcon />
        </button>
        <button type="button" className="home__button home__button--solid" onClick={onStart}>
          내 공간 시작하기
          <span aria-hidden="true">→</span>
        </button>
      </div>
    </div>
  )
}

/** The tilted space with the diffuser on it; scent ribbons drift around the bottle, passing behind and in front of it. */
function Scene() {
  const scene = useRef<HTMLDivElement>(null)
  const back = useRef<HTMLCanvasElement>(null)
  const front = useRef<HTMLCanvasElement>(null)
  useWanderingRibbons(scene, back, front)

  return (
    <div ref={scene} className="home__scene">
      <img className="home__space" src={spaceImage} alt="" width={1226} height={588} />
      <canvas ref={back} className="home__ribbons" />
      <img className="home__diffuser" src={diffuserImage} alt="" width={473} height={796} />
      <canvas ref={front} className="home__ribbons" />
    </div>
  )
}

function OpenIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M9 2.5h4.5V7M13.5 2.5 7.5 8.5M12 9.5v3a1 1 0 0 1-1 1H3.5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h3" />
    </svg>
  )
}
