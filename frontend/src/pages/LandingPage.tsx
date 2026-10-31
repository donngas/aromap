import { useRef } from 'react'
import logoMark from '../assets/logo-mark.png'
import logoSphere from '../assets/logo-sphere.png'
import { ScentLines, type PearlSprite } from '../components/ScentLines.tsx'
import './LandingPage.css'

interface LandingPageProps {
  /** Returns to the home page; this page is the service introduction. */
  onBack: () => void
}

/**
 * The logo's sphere is cut out of logo-mark.png and drawn by ScentLines, so the
 * logo's own sphere is what travels down the page. This is where it sits in
 * the mark, as a fraction of the mark image size.
 */
const LOGO_SPHERE = { x: 0.9, y: 0.7938 }

/** logo-sphere.png is 41px wide against the 360px mark; its centre is slightly off the sprite centre. */
const SPHERE_SPRITE: PearlSprite = { src: logoSphere, widthRatio: 41 / 360, centerX: 21.3 / 41, centerY: 20.7 / 41 }

// Placeholder copy until the service description is finalized; the headline
// and tagline come from the logo sheet.
export function LandingPage({ onBack }: LandingPageProps) {
  const mark = useRef<HTMLImageElement>(null)
  const ctaSection = useRef<HTMLElement>(null)
  const startButton = useRef<HTMLButtonElement>(null)

  return (
    <div className="landing">
      <ScentLines
        origin={mark}
        originPoint={LOGO_SPHERE}
        pearl={SPHERE_SPRITE}
        ctaSection={ctaSection}
        ctaAnchor={startButton}
      />

      <section className="landing__hero">
        <img ref={mark} className="landing__mark" src={logoMark} alt="" width={360} height={228} />
        <h1 className="landing__wordmark">AROMAP</h1>
        <p className="landing__tagline" lang="en">
          Visualizing scents in space
        </p>
      </section>

      <section className="landing__about" aria-labelledby="landing-about-title">
        <div className="landing__about-body">
          <h2 id="landing-about-title">
            향이 흐르는 공간을,
            <br />
            눈에 보이는 데이터로.
          </h2>
          <p>
            AROMAP은 향의 확산을 공간 안에서 시각화하는 실내 향 분석 웹 서비스입니다. 같은 디퓨저라도 놓는
            자리에 따라 향이 머무는 곳이 달라집니다. 평면도 위에서 향이 퍼지는 모습을 보고, 배치를 정하기 전에
            여러 위치를 비교해 보세요.
          </p>

          <ol className="landing__steps">
            <li>
              <h3>평면도 올리기</h3>
              <p>가지고 있는 평면도 이미지를 올리면 벽과 문을 읽어 공간을 만듭니다.</p>
            </li>
            <li>
              <h3>디퓨저 등록하기</h3>
              <p>쓰려는 제품의 유형과 용량, 사용 기간을 입력합니다.</p>
            </li>
            <li>
              <h3>놓아 보고 비교하기</h3>
              <p>공간 위에 디퓨저를 놓고, 시간이 지나며 향이 어디까지 닿는지 확인합니다.</p>
            </li>
          </ol>

          <p className="landing__caveat">
            결과는 몇 가지 공기 흐름 시나리오를 가정한 상대적인 추정이에요.
          </p>
        </div>
      </section>

      <section ref={ctaSection} className="landing__cta">
        <p>AROMAP</p>
        <button ref={startButton} type="button" className="landing__start" onClick={onBack}>
          돌아가기
        </button>
      </section>
    </div>
  )
}
