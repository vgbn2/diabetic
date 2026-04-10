import cv2
import numpy as np

class IconDetector:
    def __init__(self, min_area: int = 20, max_area: int = 5000):
        self.min_area = min_area
        self.max_area = max_area

    def detect_centroids(self, mask: np.ndarray) -> list:
        """
        Finds centroids of shapes in a binary mask using contour analysis.
        Returns a list of (x, y) tuples in pixel coordinates.
        """
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        centroids = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if self.min_area < area < self.max_area:
                M = cv2.moments(cnt)
                if M["m00"] != 0:
                    cX = int(M["m10"] / M["m00"])
                    cY = int(M["m01"] / M["m00"])
                    centroids.append((cX, cY))
        
        return centroids

    def filter_redundant_icons(self, icons: list, dist_threshold: int = 10) -> list:
        """Merges detections that are very close to each other."""
        if not icons:
            return []
            
        unique_icons = []
        for x, y in icons:
            is_new = True
            for ux, uy in unique_icons:
                dist = ((x - ux)**2 + (y - uy)**2)**0.5
                if dist < dist_threshold:
                    is_new = False
                    break
            if is_new:
                unique_icons.append((x, y))
        return unique_icons
