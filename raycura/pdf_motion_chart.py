"""Draw the assessment graph's saved Plotly traces as printable vector paths."""
import math

from reportlab.lib.colors import HexColor
from reportlab.platypus import Flowable


class MotionChart(Flowable):
    """Print one motion, including the user's selected references, marks and rule window."""

    def __init__(self, figure):
        super().__init__()
        self.figure = figure
        self.height = 142

    def wrap(self, width, height):
        self.width = width
        return width, self.height

    def draw(self):
        c = self.canv
        traces = self.figure["data"]
        angles = [value for trace in traces for value in trace["y"] if value is not None and math.isfinite(value)]
        if not angles:
            c.drawString(12, self.height / 2, "No recorded angles available.")
            return
        low, high = min(angles), max(angles)
        rough = max(high-low, 1) / 4
        decade = 10 ** math.floor(math.log10(rough))
        step = next(s * decade for s in (1, 2, 5, 10) if s * decade >= rough)
        low, high = math.floor(low/step)*step, math.ceil(high/step)*step
        if low == high:
            high += step
        x0, x1 = 37, self.width-14
        y0, y1 = 31, self.height-23

        def x(pct):
            return x0 + pct*(x1-x0)/100

        def y(angle):
            return y0 + (angle-low)*(y1-y0)/(high-low)

        def path(trace, fill=False):
            line = c.beginPath()
            first = True
            for pct, angle in zip(trace["x"],trace["y"],strict=True):
                if angle is None or not math.isfinite(angle):
                    first = True
                    continue
                if first:
                    line.moveTo(x(pct), y(angle))
                    first = False
                else:
                    line.lineTo(x(pct), y(angle))
            if fill:
                line.close()
            c.drawPath(line, stroke=int(not fill), fill=int(fill))

        for trace in traces:
            if trace.get("fill") == "toself":
                c.setFillColor(HexColor("#DCEBF2"))
                path(trace, True)
        for shape in self.figure["layout"]["shapes"]:
            if shape["type"] == "rect":
                c.setFillColor(HexColor("#FBF0D4"))
                c.saveState()
                c.setFillAlpha(.55)
                c.rect(x(shape["x0"]),y0,x(shape["x1"])-x(shape["x0"]),y1-y0,fill=1,stroke=0)
                c.restoreState()
        c.setFont("Helvetica", 7.2)
        c.setFillColor(HexColor("#425D64"))
        for i in range(round((high-low)/step)+1):
            tick = low+i*step
            c.setStrokeColor(HexColor("#92AAA8" if tick == 0 else "#D7E4E1"))
            c.setLineWidth(.55)
            c.line(x0,y(tick),x1,y(tick))
            c.drawRightString(x0-5,y(tick)-2.5,f"{tick:g}")
        for pct in range(0,101,10):
            c.setStrokeColor(HexColor("#E3EBE9"))
            c.line(x(pct),y0,x(pct),y1)
            c.drawCentredString(x(pct),y0-10,str(pct))
        c.drawCentredString((x0+x1)/2,6,"Gait cycle (%)")
        c.saveState()
        c.translate(9,(y0+y1)/2)
        c.rotate(90)
        c.drawCentredString(0,0,"Angle (°)")
        c.restoreState()
        legend_x = x0
        for trace in traces:
            marker = trace.get("marker")
            if marker:
                c.setFillColor(HexColor(marker["color"]))
                for pct, angle in zip(trace["x"],trace["y"],strict=True):
                    if angle is not None:
                        c.circle(x(pct), y(angle), 1.85, fill=1, stroke=0)
                continue
            band = trace.get("fill") == "toself"
            color = HexColor("#90B9CA" if band else trace["line"]["color"])
            c.setStrokeColor(color)
            c.setLineWidth(1.55)
            dash = trace["line"].get("dash")
            c.setDash({"dot":[1,2], "dash":[5,3]}.get(dash, []))
            if not band:
                path(trace)
            c.line(legend_x,self.height-9,legend_x+12,self.height-9)
            c.setDash()
            label = trace["name"].replace(" · ", " - ").replace("5th–95th percentile","5th-95th percentile")
            c.setFillColor(HexColor("#314D54"))
            c.drawString(legend_x+15,self.height-11.5,label)
            legend_x += 24 + c.stringWidth(label,"Helvetica",7.2)
