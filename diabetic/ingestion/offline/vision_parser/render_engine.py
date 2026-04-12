import pypdfium2 as pdfium
import cv2
import numpy as np
from PIL import Image
from pathlib import Path

class PDFRenderer:
    def __init__(self, pdf_path: str, scale: float = 8.0):
        """
        Scale 8.0 = 576 DPI (72 pts/inch * 8).
        High resolution is critical for capturing small insulin/meal icons.
        """
        self.pdf_path = Path(pdf_path)
        self.pdf = pdfium.PdfDocument(str(pdf_path))
        self.scale = scale

    def render_page(self, page_idx: int) -> np.ndarray:
        """Renders the specified page to a BGR numpy array (OpenCV format)."""
        if page_idx < 0 or page_idx >= len(self.pdf):
            raise IndexError(f"Page index {page_idx} out of range (0-{len(self.pdf)-1})")
        
        page = self.pdf[page_idx]
        bitmap = page.render(scale=self.scale)
        pil_img = bitmap.to_pil().convert("RGB")
        
        # Convert RGB to BGR for OpenCV compatibility
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    def generate_masks(self, img_bgr: np.ndarray) -> dict:
        """
        Isolates purple insulin syringes, orange meal markers, and BLUE glucose traces.
        This ignores the noise from the dense grey grid lines by targeting specific spectra.
        """
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        
        # Purple Bounds (Insulin Syringes)
        lower_purple = np.array([125, 40, 40])
        upper_purple = np.array([155, 255, 255])
        
        # Orange/Yellow Bounds (Meal Dots)
        lower_orange = np.array([5, 100, 100])
        upper_orange = np.array([25, 255, 255])

        # Blue Bounds (Glucose Trace)
        # Ottai uses a specific blue (approx HSV 100-115).
        # We allow for light blue variants seen in rasterised charts.
        lower_blue = np.array([90, 50, 50])
        upper_blue = np.array([130, 255, 255])
        
        masks = {
            "syringe": cv2.inRange(hsv, lower_purple, upper_purple),
            "meal": cv2.inRange(hsv, lower_orange, upper_orange),
            "glucose": cv2.inRange(hsv, lower_blue, upper_blue)
        }
        return masks
