import AppKit

let size = 1024
let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                              bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                              colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
func color(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat) {
    NSColor(srgbRed: r, green: g, blue: b, alpha: 1).setFill()
}
func rounded(_ x: CGFloat, _ y: CGFloat, _ width: CGFloat, _ height: CGFloat, _ radius: CGFloat) {
    NSBezierPath(roundedRect: NSRect(x: x, y: y, width: width, height: height),
                 xRadius: radius, yRadius: radius).fill()
}
color(0.13, 0.14, 0.15)
rounded(54, 54, 916, 916, 205)
color(0.545, 0.902, 0.733)
let arrow = NSBezierPath()
arrow.move(to: NSPoint(x: 236, y: 632))
arrow.line(to: NSPoint(x: 716, y: 632))
arrow.line(to: NSPoint(x: 804, y: 694))
arrow.line(to: NSPoint(x: 716, y: 756))
arrow.line(to: NSPoint(x: 236, y: 756))
arrow.close()
arrow.fill()
color(0.949, 0.933, 0.902)
rounded(236, 450, 344, 116, 58)
rounded(236, 270, 344, 116, 58)
NSGraphicsContext.restoreGraphicsState()
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
