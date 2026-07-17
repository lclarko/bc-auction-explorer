import { useState } from "react";

type ListingImageProps = {
  alt: string;
  imageUrls: string[];
};

export function ListingImage({ alt, imageUrls }: ListingImageProps) {
  const source = imageUrls[0];
  const [failedSource, setFailedSource] = useState<string | null>(null);

  if (!source || failedSource === source) {
    return <div aria-label="Image not available" className="listing-image listing-image--fallback" role="img" />;
  }

  return (
    <img
      alt={alt}
      className="listing-image"
      loading="lazy"
      onError={() => setFailedSource(source)}
      referrerPolicy="no-referrer"
      src={source}
    />
  );
}
