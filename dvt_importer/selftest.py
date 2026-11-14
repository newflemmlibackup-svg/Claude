"""Selbsttest (`--selftest`): prüft, ob das Programm - auch als fertig gebaute
.exe/.app - komprimierte Fremddaten lesen und ein gültiges Medium schreiben kann.
Rückgabewert 0 = in Ordnung."""
from __future__ import annotations

import tempfile
import traceback
from pathlib import Path


def run() -> int:
    try:
        import numpy as np
        import pydicom
        from pydicom.dataset import Dataset, FileMetaDataset
        from pydicom.uid import (CTImageStorage, ExplicitVRLittleEndian, JPEG2000Lossless,
                                 RLELossless, generate_uid)

        import libjpeg  # noqa: F401  (JPEG-Decoder muss im Programmpaket enthalten sein)

        from .converter import convert_series_list
        from .scanner import scan_source

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "quelle"
            src.mkdir()
            study, series = generate_uid(), generate_uid()
            expected = {}
            for i in (1, 2, 3, 4, 6, 7, 8):          # Schicht 5 fehlt absichtlich
                arr = (np.arange(64 * 64, dtype=np.uint16).reshape(64, 64) + i * 10)
                expected[i] = arr
                ds = Dataset()
                ds.file_meta = FileMetaDataset()
                ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
                ds.file_meta.MediaStorageSOPClassUID = CTImageStorage
                ds.SOPClassUID, ds.SOPInstanceUID = CTImageStorage, generate_uid()
                ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
                ds.StudyInstanceUID, ds.SeriesInstanceUID = study, series
                ds.PatientName, ds.PatientID, ds.Modality = "Test^Selbst", "T1", "CT"
                ds.Rows = ds.Columns = 64
                ds.BitsAllocated = ds.BitsStored = 16
                ds.HighBit, ds.PixelRepresentation, ds.SamplesPerPixel = 15, 0, 1
                ds.PhotometricInterpretation = "MONOCHROME2"
                ds.InstanceNumber = i
                ds.ImagePositionPatient = [0, 0, i * 0.3]
                ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
                ds.PixelSpacing = [0.3, 0.3]
                ds.PixelData = arr.tobytes()
                # Abwechselnd JPEG 2000 und RLE komprimiert.
                ds.compress(JPEG2000Lossless if i % 2 else RLELossless, arr,
                            generate_instance_uid=False)
                ds.save_as(str(src / f"IMG{i:03d}"), enforce_file_format=True)

            scan = scan_source(src)
            assert len(scan.series) == 1 and scan.series[0].num_missing == 1, "Analyse fehlerhaft"
            result = convert_series_list(scan.series, Path(tmp) / "ziel")
            assert result.verified and result.images_written == 8, "Ausgabe fehlerhaft"
            assert result.black_missing == 1 and result.black_damaged == 0, result.per_series_log
            from pydicom.fileset import FileSet

            for inst in FileSet(str(Path(tmp) / "ziel" / "DICOMDIR")):
                out = pydicom.dcmread(inst.path)
                n = int(out.InstanceNumber)
                if n in expected:
                    assert (out.pixel_array == expected[n]).all(), f"Bildinhalt Schicht {n} verändert"
        print("Selbsttest bestanden.")
        return 0
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1
