import AppKit
import Foundation
import PDFKit
import Vision

struct OCRLine {
    let text: String
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

func recognize(_ image: NSImage) throws -> [OCRLine] {
    var proposedRect = CGRect(origin: .zero, size: image.size)
    guard let cgImage = image.cgImage(
        forProposedRect: &proposedRect,
        context: nil,
        hints: nil
    ) else {
        return []
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["en-US"]
    request.usesLanguageCorrection = true
    try VNImageRequestHandler(cgImage: cgImage).perform([request])
    return (request.results ?? [])
        .compactMap { observation -> OCRLine? in
            guard let text = observation.topCandidates(1).first?.string else {
                return nil
            }
            let box = observation.boundingBox
            return OCRLine(
                text: text,
                x: Double(box.minX),
                y: Double(box.minY),
                width: Double(box.width),
                height: Double(box.height)
            )
        }
        .sorted {
            if abs($0.y - $1.y) > 0.006 {
                return $0.y > $1.y
            }
            return $0.x < $1.x
        }
}

func recognizePDF(_ url: URL) throws -> [OCRLine] {
    guard let document = PDFDocument(url: url) else {
        return []
    }
    var lines: [OCRLine] = []
    for pageIndex in 0..<document.pageCount {
        guard let page = document.page(at: pageIndex) else {
            continue
        }
        let bounds = page.bounds(for: .mediaBox)
        let scale = max(1.0, min(3.0, 1800.0 / max(bounds.width, bounds.height)))
        let image = page.thumbnail(
            of: CGSize(width: bounds.width * scale, height: bounds.height * scale),
            for: .mediaBox
        )
        lines.append(contentsOf: try recognize(image))
    }
    return lines
}

var output: [[String: Any]] = []
for rawPath in CommandLine.arguments.dropFirst() {
    let url = URL(fileURLWithPath: rawPath)
    let lines: [OCRLine]
    if url.pathExtension.lowercased() == "pdf" {
        lines = try recognizePDF(url)
    } else if let image = NSImage(contentsOf: url) {
        lines = try recognize(image)
    } else {
        lines = []
    }
    let lineObjects: [[String: Any]] = lines.map {
        [
            "text": $0.text,
            "x": $0.x,
            "y": $0.y,
            "width": $0.width,
            "height": $0.height,
        ]
    }
    let item: [String: Any] = [
        "path": url.standardizedFileURL.path,
        "text": lines.map(\.text).joined(separator: "\n"),
        "lines": lineObjects,
    ]
    output.append(item)
}

let json = try JSONSerialization.data(
    withJSONObject: output,
    options: [.sortedKeys, .fragmentsAllowed]
)
FileHandle.standardOutput.write(json)
