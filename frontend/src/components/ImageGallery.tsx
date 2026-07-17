import { useState } from "react";

import { ListingImage } from "./ListingImage";

type ImageGalleryProps = {
  imageUrls: string[];
  title: string;
};

export function ImageGallery({ imageUrls, title }: ImageGalleryProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [failedUrls, setFailedUrls] = useState<ReadonlySet<string>>(() => new Set());
  const selectedUrl = imageUrls[selectedIndex];

  return (
    <div className="image-gallery">
      {selectedUrl && !failedUrls.has(selectedUrl) ? (
        <img
          alt={title}
          className="listing-image image-gallery__main"
          onError={() => setFailedUrls((urls) => new Set(urls).add(selectedUrl))}
          referrerPolicy="no-referrer"
          src={selectedUrl}
        />
      ) : (
        <ListingImage alt={title} imageUrls={[]} />
      )}
      {imageUrls.length > 1 ? (
        <div aria-label="Listing images" className="image-gallery__thumbnails" role="group">
          {imageUrls.map((imageUrl, index) => (
            <button
              aria-label={`Show image ${index + 1} of ${imageUrls.length}`}
              aria-pressed={index === selectedIndex}
              className="image-gallery__thumbnail"
              key={imageUrl}
              onClick={() => setSelectedIndex(index)}
              type="button"
            >
              <img alt="" loading="lazy" referrerPolicy="no-referrer" src={imageUrl} />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
