import { useState } from "react";

type ListingImageProps = {
  alt: string;
  imageUrls: string[];
};

export function ListingImage({ alt, imageUrls }: ListingImageProps) {
  const [failed, setFailed] = useState(false);
  const source = imageUrls[0];

  if (!source || failed) {
    return <div aria-label="Image not available" className="listing-image listing-image--fallback" role="img" />;
  }

  return (
    <img
      alt={alt}
      className="listing-image"
      loading="lazy"
      onError={() => setFailed(true)}
      referrerPolicy="no-referrer"
      src={source}
    />
  );
}
