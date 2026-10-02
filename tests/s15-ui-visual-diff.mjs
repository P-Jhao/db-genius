import { readFileSync } from 'node:fs'

async function compareScreenshots(browser, left, right, names) {
  const probe = await browser.newPage()
  const differences = {}
  try {
    for (const name of names) {
      const before = readFileSync(left[name]).toString('base64')
      const after = readFileSync(right[name]).toString('base64')
      differences[name] = await probe.evaluate(async ({ beforePng, afterPng }) => {
        async function decode(png) {
          const image = new Image()
          image.src = `data:image/png;base64,${png}`
          await image.decode()
          return image
        }
        const [a, b] = await Promise.all([decode(beforePng), decode(afterPng)])
        if (a.width !== b.width || a.height !== b.height) {
          return { width: a.width, height: a.height, candidateWidth: b.width, candidateHeight: b.height, changedPercent: 100 }
        }
        const canvas = document.createElement('canvas')
        canvas.width = a.width
        canvas.height = a.height
        const context = canvas.getContext('2d', { willReadFrequently: true })
        if (!context) throw new Error('Canvas 2D is unavailable for screenshot comparison')
        context.drawImage(a, 0, 0)
        const first = context.getImageData(0, 0, a.width, a.height).data
        context.clearRect(0, 0, a.width, a.height)
        context.drawImage(b, 0, 0)
        const second = context.getImageData(0, 0, b.width, b.height).data
        let changed = 0
        let absoluteDifference = 0
        for (let index = 0; index < first.length; index += 4) {
          const delta = Math.max(Math.abs(first[index] - second[index]),
            Math.abs(first[index + 1] - second[index + 1]), Math.abs(first[index + 2] - second[index + 2]))
          if (delta > 16) changed += 1
          absoluteDifference += delta
        }
        const pixels = a.width * a.height
        return {
          width: a.width,
          height: a.height,
          changedPercent: Number((changed * 100 / pixels).toFixed(2)),
          meanChannelDifference: Number((absoluteDifference / (pixels * 3)).toFixed(2)),
        }
      }, { beforePng: before, afterPng: after })
    }
  } finally {
    await probe.close()
  }
  return differences
}

export { compareScreenshots }
