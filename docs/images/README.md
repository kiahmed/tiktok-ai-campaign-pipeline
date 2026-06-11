# Product images (hosted on GitHub Pages)

Drop product image files in this folder, commit and push, and GitHub Pages will
serve them as public URLs you can use in `config/product_images.json`.

## URL pattern

GitHub Pages serves this repo's `docs/` folder, so a file here:

```
docs/images/oil-front.jpg
```

is available at:

```
https://kiahmed.github.io/tiktok-ai-campaign-pipeline/images/oil-front.jpg
```

(Replace the filename. If you later add a custom domain via `docs/CNAME`, swap
the host for your domain, e.g. `https://www.solutionjet.net/images/oil-front.jpg`.)

## How to use

1. Add your images here (e.g. `oil-front.jpg`, `oil-angle.jpg`, `oil-lifestyle.jpg`).
2. Commit + push to `main`.
3. Add the public URLs to `config/product_images.json`:

```json
{
  "product_image_urls": [
    "https://kiahmed.github.io/tiktok-ai-campaign-pipeline/images/oil-front.jpg",
    "https://kiahmed.github.io/tiktok-ai-campaign-pipeline/images/oil-angle.jpg",
    "https://kiahmed.github.io/tiktok-ai-campaign-pipeline/images/oil-lifestyle.jpg"
  ]
}
```

4. Restart the API server. Each video's product shot then uses a random image
   from this list.

## Tips

- Use square or vertical images; the pipeline pads them to 9:16 with a blurred
  fill, but a tighter crop looks best.
- Keep filenames URL-safe (no spaces): use `oil-front.jpg`, not `oil front.jpg`.
- Pages can take ~1 minute to publish after a push.
