import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ImageGallery } from "./ImageGallery";
import { ListingImage } from "./ListingImage";

describe("listing images", () => {
  it("allows a new image source after a previous source failed", () => {
    const { rerender } = render(<ListingImage alt="First image" imageUrls={["https://example.test/first.jpg"]} />);

    fireEvent.error(screen.getByRole("img", { name: "First image" }));
    expect(screen.getByRole("img", { name: "Image not available" })).toBeInTheDocument();

    rerender(<ListingImage alt="Second image" imageUrls={["https://example.test/second.jpg"]} />);
    expect(screen.getByRole("img", { name: "Second image" })).toHaveAttribute(
      "src",
      "https://example.test/second.jpg",
    );
  });

  it("selects an available image when the gallery receives a new image list", () => {
    const { rerender } = render(
      <ImageGallery
        imageUrls={["https://example.test/first.jpg", "https://example.test/second.jpg"]}
        title="First listing"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Show image 2 of 2" }));
    rerender(<ImageGallery imageUrls={["https://example.test/third.jpg"]} title="Second listing" />);

    expect(screen.getByRole("img", { name: "Second listing" })).toHaveAttribute(
      "src",
      "https://example.test/third.jpg",
    );
  });
});
