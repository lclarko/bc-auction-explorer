import { useState } from "react";

import { ListingImage } from "./ListingImage";

type ImageGalleryProps = {
  imageUrls: string[];
  title: string;
};

export function ImageGallery({ imageUrls, title }: ImageGalleryProps) {
  const [selectedImageUrl, setSelectedImageUrl] = useState<string | null>(null);
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null);
  const selectedUrl =
    selectedImageUrl && imageUrls.includes(selectedImageUrl) ? selectedImageUrl : (imageUrls[0] ?? null);

  return (
    <div className="image-gallery">
      {selectedUrl && failedImageUrl !== selectedUrl ? (
        <img
          alt={title}
          className="listing-image image-gallery__main"
          onError={() => setFailedImageUrl(selectedUrl)}
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
              aria-pressed={imageUrl === selectedUrl}
              className="image-gallery__thumbnail"
              key={imageUrl}
              onClick={() => setSelectedImageUrl(imageUrl)}
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
