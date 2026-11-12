"""Record-data subcommands: gen-data, decode, compare, gen-fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, NoReturn

from .._common import (
    _add_compact_arg,
    _add_copybook_args,
    _add_debug_lines_arg,
    _add_encoding_arg,
    _add_output_arg,
    _fail,
    _json_out,
    _read_source,
    _verbatim_out,
)

# -- Subcommand: gen-data -----------------------------------------------------


def _build_gen_data_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "gen-data",
        help="Generate synthetic CSV test data from a copybook record layout",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser gen-data CUSTOMER.cpy --rows 100 --seed 7 -o out.csv\n"
            "  cobol-parser gen-data CUSTOMER.cpy --list-records"
        ),
    )
    p.add_argument("file", help="Path to the copybook (or COBOL source) file")
    _add_encoding_arg(p)
    p.add_argument(
        "--rows",
        "-n",
        type=int,
        default=10,
        metavar="N",
        help="Number of records to generate (default: 10)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="RNG seed for reproducible output (default: random, reported in --describe)",
    )
    p.add_argument(
        "--record",
        default=None,
        metavar="NAME",
        help="Level-01 record to generate from (default: the first in the copybook)",
    )
    p.add_argument(
        "--list-records",
        action="store_true",
        help="List the level-01 records in the copybook and exit",
    )
    p.add_argument(
        "--describe",
        action="store_true",
        help="Emit the resolved layout and rows as JSON instead of CSV",
    )
    p.add_argument(
        "--header-style",
        choices=["short", "path"],
        default="short",
        help="CSV header naming: short field name (default) or dotted record path",
    )
    p.add_argument(
        "--include-filler",
        action="store_true",
        help="Include FILLER items as columns (skipped by default)",
    )
    p.add_argument(
        "--include-redefines",
        action="store_true",
        help="Include REDEFINES fields, which alias bytes another column covers",
    )
    p.add_argument(
        "--no-expand-occurs",
        action="store_true",
        help="Emit only the first occurrence of each OCCURS table",
    )
    p.add_argument(
        "--max-occurs",
        type=int,
        default=None,
        metavar="N",
        help="Cap the occurrences expanded per OCCURS table",
    )
    p.add_argument(
        "--no-semantic",
        action="store_true",
        help="Disable field-name value heuristics (NAME, CITY, DATE, ...)",
    )
    p.add_argument(
        "--ignore-values",
        action="store_true",
        help="Ignore VALUE clauses and level-88 values when generating",
    )
    p.add_argument(
        "--unique",
        action="append",
        default=[],
        metavar="FIELD",
        help="Field whose column must hold distinct values (repeatable)",
    )
    p.add_argument(
        "--blank-rate",
        type=float,
        default=0.0,
        metavar="RATE",
        help="Fraction of cells (0.0-1.0) to leave blank (default: 0.0)",
    )
    p.add_argument(
        "--format",
        dest="output_format",
        choices=["csv", "json", "record", "hex"],
        default="csv",
        help=(
            "csv (default) / json display values; record writes the real "
            "COBOL record image (COMP-3 packed, COMP big-endian binary, "
            "signed DISPLAY overpunched); hex is that image annotated "
            "field by field"
        ),
    )
    p.add_argument(
        "--charset",
        choices=["ascii", "ebcdic"],
        default="ascii",
        help="Encoding of DISPLAY bytes for --format record/hex (default: ascii)",
    )
    p.add_argument(
        "--endian",
        choices=["auto", "big", "little", "native"],
        default="auto",
        help=(
            "Byte order for COMP-5 and COMP-1/COMP-2 (default: auto -- "
            "big-endian for --charset ebcdic, host order otherwise). "
            "COMP/COMP-4 are always big-endian"
        ),
    )
    p.add_argument(
        "--record-format",
        choices=["fixed", "variable", "variable-bare", "auto"],
        # Not "fixed": the default has to stay distinguishable from an
        # explicit --record-format fixed, so that --record-varying (which is
        # a statement that records are *not* fixed) can default to auto
        # without overriding a caller who really did ask for fixed.
        default=None,
        help=(
            "Record length for --format record/hex: fixed (default) writes "
            "every record at the layout's full length, as RECFM=F/FB expects; "
            "variable writes only the OCCURS DEPENDING ON occurrences each "
            "record's own counter names, behind the 4-byte RDW that RECFM=V/VB "
            "uses to delimit them; variable-bare is the same records without "
            "the RDW; auto picks variable when the layout has a DEPENDING ON "
            "table and fixed otherwise"
        ),
    )
    p.add_argument(
        "--record-varying",
        default=None,
        metavar="MIN:MAX",
        help=(
            "Record length range, as an FD's RECORD VARYING FROM MIN TO MAX "
            "declares. Only needed for a bare copybook, which carries no FD: "
            "given a whole COBOL program, the clause is read off the record "
            "itself. Implies a variable record format unless --record-format "
            "says otherwise"
        ),
    )
    p.add_argument(
        "--record-separator",
        choices=["none", "newline"],
        default="none",
        help=(
            "Bytes between records for --format record (default: none, a "
            "true fixed-length RECFM=F image)"
        ),
    )
    _add_compact_arg(p)
    _add_copybook_args(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_gen_data)


def _warn_layout(warnings: list[str]) -> None:
    """Say on stderr that a record layout is short a ``COPY`` member.

    ``gen-data``, ``decode`` and ``compare`` frame every record by the
    layout's length, so a ``COPY`` left unexpanded (no ``--copybook-path``,
    or its member not found there) silently drops fields and shortens every
    record. Never silent: this is the one place that says so.
    """
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)


def _encoding_options(args: argparse.Namespace) -> Any:
    """Build the EncodingOptions the record-image formats are rendered with."""
    from ...generators.data.encoding import (
        Charset,
        EncodingOptions,
        Endian,
        RecordFormat,
    )

    chosen = getattr(args, "record_format", None)
    if chosen is None:
        # Asking for a length range is itself saying the records vary, so
        # --record-varying alone reaches auto rather than silently writing
        # the fixed-length file the caller just said this is not.
        chosen = "auto" if getattr(args, "record_varying", None) else "fixed"
    return EncodingOptions(
        charset=Charset(args.charset),
        endian=Endian(args.endian),
        record_separator=b"\n" if args.record_separator == "newline" else b"",
        record_format=RecordFormat(chosen),
    )


def _cmd_gen_data(args: argparse.Namespace) -> None:
    from ...generators.data import (
        CopybookDataGenerator,
        CopybookLayoutError,
        DataGeneratorOptions,
        parse_copybook_records,
    )

    source = _read_source(args.file, getattr(args, "encoding", None))
    copybook_paths = args.copybook_path or None

    if args.list_records:
        layout_warnings: list[str] = []
        try:
            records = parse_copybook_records(
                source,
                filename=args.file,
                copybook_paths=copybook_paths,
                warnings=layout_warnings,
            )
        except CopybookLayoutError as exc:
            _fail(str(exc))
        _warn_layout(layout_warnings)
        _json_out(
            {
                "source_file": args.file,
                "records": [
                    {"name": r.name, "level": r.level, "size": r.calculate_size()}
                    for r in records
                ],
            },
            args.compact,
            getattr(args, "output", None),
        )
        return

    wants_record_image = args.output_format in ("record", "hex")

    try:
        options = DataGeneratorOptions(
            rows=args.rows,
            seed=args.seed,
            include_filler=args.include_filler,
            include_redefines=args.include_redefines,
            expand_occurs=not args.no_expand_occurs,
            max_occurs=args.max_occurs,
            respect_values=not args.ignore_values,
            use_condition_values=not args.ignore_values,
            semantic_hints=not args.no_semantic,
            header_style=args.header_style,
            unique_fields=tuple(args.unique),
            blank_rate=args.blank_rate,
            record_varying=_parse_record_varying(args.record_varying),
        )
    except ValueError as exc:
        _fail(str(exc))

    if wants_record_image:
        # A record image has to account for every byte, which the
        # column-shaped defaults deliberately do not -- see
        # DataGeneratorOptions.for_record_image. Overriding silently would
        # make --include-filler/--max-occurs look ignored, so say so.
        adjusted = options.for_record_image()
        if adjusted != options:
            print(
                f"note: --format {args.output_format} lays out every byte of "
                "the record, so FILLER is included, REDEFINES excluded, and "
                "every OCCURS occurrence expanded",
                file=sys.stderr,
            )
        options = adjusted

    try:
        dataset = CopybookDataGenerator(options).generate_from_source(
            source,
            filename=args.file,
            record=args.record,
            copybook_paths=copybook_paths,
        )
    except CopybookLayoutError as exc:
        _fail(str(exc))
    # Whatever the format: a --record-varying range clamped or ignored to
    # fit the layout is otherwise invisible in CSV/JSON/record output.
    for caveat in dataset.caveats:
        print(f"warning: {caveat}", file=sys.stderr)

    output_path = getattr(args, "output", None)

    if args.describe or args.output_format == "json":
        _json_out(
            {"source_file": args.file, **dataset.to_dict()},
            args.compact,
            output_path,
        )
        return

    if args.output_format == "hex":
        text = dataset.to_hex_dump(_encoding_options(args))
        if output_path:
            try:
                with open(output_path, "w", encoding="utf-8") as handle:
                    handle.write(text)
            except OSError as e:
                _fail(f"Cannot write output file: {e}")
        else:
            print(text, end="")
        return

    if args.output_format == "record":
        # Encode once and reuse the bytes for whichever destination follows.
        # Encoding here and then calling dataset.write_records() would encode
        # the whole dataset a second time -- twice the CPU, and both copies
        # resident at once, which is a real ceiling on a large --rows.
        encoding = _encoding_options(args)
        try:
            raw = dataset.to_records(encoding)
        except CopybookLayoutError as exc:
            _fail(str(exc))
        for caveat in _record_caveats(dataset, encoding):
            print(f"note: {caveat}", file=sys.stderr)
        for note in _record_length_notes(dataset, encoding):
            print(f"note: {note}", file=sys.stderr)
        if output_path:
            # Binary mode is not incidental: a COMP field routinely contains
            # 0x0A, which a text-mode write would translate on Windows.
            try:
                with open(output_path, "wb") as handle:
                    handle.write(raw)
            except OSError as e:
                _fail(f"Cannot write output file: {e}")
        else:
            # Same reason, on the way to stdout: go through the buffer so
            # nothing re-encodes or newline-translates the bytes.
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()
        return

    if output_path:
        # Write through the csv module so embedded newlines round-trip.
        try:
            dataset.write_csv(output_path)
        except OSError as e:
            _fail(f"Cannot write output file: {e}")
    else:
        print(dataset.to_csv(), end="")


def _parse_record_varying(raw: str | None) -> tuple[int, int] | None:
    """Parse ``--record-varying MIN:MAX`` into a length range.

    ``MIN-MAX`` is accepted too, since that is how the range reads in an FD
    (``FROM 47 TO 80``) and a hyphen is the likelier typo of the two.
    """
    if raw is None:
        return None
    parts = raw.replace("-", ":").split(":")
    if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):
        _fail(f"--record-varying expects MIN:MAX (two integers), got {raw!r}")
    return (int(parts[0]), int(parts[1]))


def _record_caveats(dataset: Any, opts: Any) -> list[str]:
    """Reasons a written record image may not match a real compiler's."""
    from ...generators.data.encoding import encoding_caveats

    return encoding_caveats(dataset.fields, opts, varying=dataset.varying)


def _record_length_notes(dataset: Any, opts: Any) -> list[str]:
    """The LRECL a reader of ``--format record`` output has to be told.

    ``--format hex`` prints this in its own header; the raw bytes have no
    header to print it in, and a record image whose length nobody states is
    a file nobody can read back.
    """
    from ...generators.data.encoding import RecordFormat

    lengths = dataset.record_lengths(opts)
    if not lengths:
        return []
    fmt = opts.resolved_format(dataset.fields, varying=dataset.varying is not None)
    framed = " (RDW included)" if fmt is RecordFormat.VARIABLE else ""
    low, high = min(lengths), max(lengths)
    span = f"{high}" if low == high else f"{low} to {high}"
    notes = [
        f"{fmt.value} record length: {span} bytes across "
        f"{len(lengths)} records{framed}"
    ]
    varying = dataset.varying
    if varying is not None and fmt.is_variable:
        # What this file *happens* to contain is not what the dataset holding
        # it has to be allocated for: LRECL comes from the declared maximum,
        # which a short run of --rows may never actually hit.
        rdw = 4 if fmt is RecordFormat.VARIABLE else 0
        notes.append(
            f"declared RECORD VARYING FROM {varying.minimum} TO "
            f"{varying.maximum}, so LRECL is {varying.maximum + rdw}"
            + (" (max record + RDW)" if rdw else "")
        )
    return notes


def _add_record_file_args(p: argparse.ArgumentParser) -> None:
    """How a record image file is encoded and framed -- decode and compare."""
    p.add_argument(
        "--charset",
        choices=["ascii", "ebcdic"],
        default="ascii",
        help="Encoding of the file's DISPLAY bytes (default: ascii)",
    )
    p.add_argument(
        "--endian",
        choices=["auto", "big", "little", "native"],
        default="auto",
        help=(
            "Byte order for COMP-5 and COMP-1/COMP-2 (default: auto -- "
            "big-endian for --charset ebcdic, host order otherwise). "
            "COMP/COMP-4 are always big-endian"
        ),
    )
    p.add_argument(
        "--record-format",
        choices=["fixed", "variable", "variable-bare", "auto"],
        default=None,
        help=(
            "How the file frames its records: fixed (default) cuts every "
            "record at the layout's length, as RECFM=F/FB writes them; "
            "variable reads the 4-byte RDW in front of each record, as "
            "RECFM=V/VB writes it; variable-bare has no RDW and is framed by "
            "the layout's own OCCURS DEPENDING ON counters; auto picks "
            "variable when the layout has a DEPENDING ON table or --copybook "
            "is a whole program whose FD declares RECORD VARYING -- the same "
            "choice gen-data's auto makes for the same source"
        ),
    )
    p.add_argument(
        "--record-length",
        type=int,
        default=None,
        metavar="N",
        help=(
            "LRECL to cut fixed-length records at, when the file's records "
            "are longer than the copybook describes (trailing slack, or a "
            "copybook covering only a prefix). Defaults to the FD's LRECL "
            "when the source is a whole program"
        ),
    )
    p.add_argument(
        "--record-separator",
        choices=["none", "newline"],
        default="none",
        help="Bytes separating records in the file (default: none)",
    )


def _build_decode_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "decode",
        help="Decode a record image / EBCDIC flat file through a copybook layout",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser decode CUSTOMER.DAT --copybook CUSTOMER.cpy "
            "--charset ebcdic\n"
            "  cobol-parser decode ORDER.VB --copybook ORDER.cpy "
            "--record-format variable --format hex\n"
            "  cobol-parser decode CUSTOMER.DAT --copybook CUSTOMER.cpy "
            "--list-views\n"
            "  cobol-parser decode CUSTOMER.DAT --copybook CUSTOMER.cpy "
            "--view ADDR-OVERSEAS --max-records 20"
        ),
    )
    p.add_argument(
        "file",
        nargs="?",
        default=None,
        help=(
            "Path to the data file (record images). Optional with "
            "--list-views, which only reads the copybook"
        ),
    )
    p.add_argument(
        "--copybook",
        "-c",
        required=True,
        metavar="FILE",
        help="Copybook (or COBOL program) whose record layout describes the data",
    )
    p.add_argument(
        "--record",
        default=None,
        metavar="NAME",
        help="Level-01 record in the copybook to decode through (default: the first)",
    )
    p.add_argument(
        "--view",
        default=None,
        metavar="NAME",
        help=(
            "REDEFINES overlay to read the bytes through, by its own name or "
            "its qualified path (default: the record as declared)"
        ),
    )
    p.add_argument(
        "--list-views",
        action="store_true",
        help=(
            "List the record's layout and every REDEFINES overlay of it, with "
            "byte offsets, and exit without reading the data file"
        ),
    )
    p.add_argument(
        "--format",
        dest="output_format",
        choices=["csv", "json", "hex"],
        default="csv",
        help=(
            "csv (default) is one row per record; json adds every field's "
            "offset, length and raw bytes; hex is a byte pane whose lines are "
            "the field boundaries"
        ),
    )
    _add_record_file_args(p)
    p.add_argument(
        "--max-records",
        type=int,
        default=None,
        metavar="N",
        help="Decode at most N records (default: all of them)",
    )
    p.add_argument(
        "--skip",
        type=int,
        default=0,
        metavar="N",
        help="Skip the first N records before decoding (default: 0)",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit 1 when any field failed to decode or the file had trailing "
            "bytes -- the copybook probably does not match the data"
        ),
    )
    _add_copybook_args(p)
    _add_compact_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_decode)


def _decode_encoding_options(args: argparse.Namespace) -> Any:
    """The EncodingOptions a data file is read back through."""
    from ...generators.data.encoding import (
        Charset,
        EncodingOptions,
        Endian,
        RecordFormat,
    )

    return EncodingOptions(
        charset=Charset(args.charset),
        endian=Endian(args.endian),
        record_separator=b"\n" if args.record_separator == "newline" else b"",
        record_format=RecordFormat(args.record_format or "fixed"),
    )


def _cmd_decode(args: argparse.Namespace) -> None:
    from ...generators.data.decoding import (
        RecordDecoder,
        RecordDecodingError,
        decoded_hex_dump,
    )
    from ...layout.errors import CopybookLayoutError

    # Checked here rather than left to the decoder: a negative --record-length
    # surfaced as "the layout is zero bytes long", --record-length 0 was
    # silently replaced by the layout's own length, and a negative
    # --max-records decoded nothing without a word.
    if args.record_length is not None and args.record_length <= 0:
        _fail("--record-length must be a positive number of bytes")
    if args.max_records is not None and args.max_records < 0:
        _fail("--max-records cannot be negative")
    if args.skip < 0:
        _fail("--skip cannot be negative")
    encoding = _decode_encoding_options(args)
    try:
        decoder = RecordDecoder.from_copybook_file(
            args.copybook,
            record=args.record,
            opts=encoding,
            record_length=args.record_length,
            copybook_paths=args.copybook_path or None,
        )
    except CopybookLayoutError as exc:
        _fail(str(exc))
    except OSError as exc:
        _fail(f"Cannot read copybook: {exc}")
    except UnicodeDecodeError as exc:
        # A non-UTF-8 copybook (a Latin-1 accent in a comment): a one-line
        # error, as compare gives, not a traceback (#496).
        _fail(f"Cannot read copybook {args.copybook}: {exc}")
    _warn_layout(decoder.layout_warnings)

    output_path = getattr(args, "output", None)

    if args.list_views:
        # The layout alone, with no data file needed: this is what an editor
        # asks for to draw a record map, and what a user runs to find out
        # what --view will accept.
        _json_out(
            {"copybook": args.copybook, **decoder.views.to_dict()},
            args.compact,
            output_path,
        )
        return

    if args.file is None:
        _fail("decode needs a data file (or --list-views, which does not)")

    try:
        result = decoder.decode_file(
            args.file,
            view=args.view,
            max_records=args.max_records,
            skip=args.skip,
        )
    except RecordDecodingError as exc:
        _fail(str(exc))
    except OSError as exc:
        _fail(f"Cannot read data file: {exc}")

    for caveat in result.caveats:
        if caveat not in decoder.layout_warnings:  # already said, as a warning
            print(f"note: {caveat}", file=sys.stderr)
    if result.trailing:
        # Never silent: a tail that is not a whole record almost always means
        # the record length is wrong, and a table of plausible rows above it
        # is exactly how that goes unnoticed.
        print(
            f"warning: {len(result.trailing)} trailing bytes are not a whole "
            f"record -- check --record-length / --record-format",
            file=sys.stderr,
        )
    if result.error_count:
        print(
            f"warning: {result.error_count} field(s) did not decode cleanly "
            "-- run with --format json or hex to see which",
            file=sys.stderr,
        )

    if args.output_format == "json":
        _json_out(
            {"data_file": args.file, "copybook": args.copybook, **result.to_dict()},
            args.compact,
            output_path,
        )
    elif args.output_format == "hex":
        _verbatim_out(decoded_hex_dump(result, encoding), output_path)
    else:
        _verbatim_out(result.to_csv(), output_path)

    if args.strict and (result.error_count or result.trailing):
        sys.exit(1)


def _build_compare_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "compare",
        help=(
            "Compare two record files field by field through a copybook "
            "(expected vs actual output of a batch run)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit status is 0 when the files are equal, 1 when they differ, "
            "and 2 when\nthe comparison could not be made -- like cmp and "
            "diff, so a test or CI\nstep can gate on it directly.\n\n"
            "Examples:\n"
            "  cobol-parser compare CUST.EXPECTED CUST.ACTUAL --copybook "
            "CUSTOMER.cpy --charset ebcdic\n"
            "  cobol-parser compare BASE.DAT OUT.DAT -c CUSTOMER.cpy "
            "--key CUST-ID --ignore LAST-UPDATE-TS\n"
            "  cobol-parser compare BASE.VB OUT.VB -c ORDER.cpy "
            "--record-format variable --format json"
        ),
    )
    p.add_argument("expected", help="The baseline record file")
    p.add_argument("actual", help="The record file under test")
    p.add_argument(
        "--copybook",
        "-c",
        required=True,
        metavar="FILE",
        help="Copybook (or COBOL program) whose record layout describes both files",
    )
    p.add_argument(
        "--record",
        default=None,
        metavar="NAME",
        help="Level-01 record in the copybook to read through (default: the first)",
    )
    p.add_argument(
        "--view",
        default=None,
        metavar="NAME",
        help="REDEFINES overlay to read both files through (default: the record)",
    )
    p.add_argument(
        "--key",
        action="append",
        default=[],
        metavar="FIELD",
        help=(
            "Pair records on this field instead of by position (repeatable, "
            "for a multi-field key). An inserted or deleted record is then "
            "reported once instead of shifting every record after it"
        ),
    )
    p.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="FIELD",
        help=(
            "Leave a field out of the compare (repeatable): a column "
            "(QTY(2)), a field name (QTY, every occurrence), or a group "
            "(everything under it). For timestamps, run ids and the like"
        ),
    )
    p.add_argument(
        "--compare-bytes",
        action="store_true",
        help=(
            "Compare raw bytes rather than decoded values (a C and an F sign "
            "nibble then differ), and report bytes no field covers"
        ),
    )
    p.add_argument(
        "--max-differences",
        type=int,
        default=None,
        metavar="N",
        help="Report at most N differing records (the counts stay exact)",
    )
    p.add_argument(
        "--format",
        dest="output_format",
        choices=["text", "json"],
        default="text",
        help="text (default) is a report to read; json is every difference in full",
    )
    _add_record_file_args(p)
    _add_copybook_args(p)
    _add_compact_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_compare)


def _compare_fail(message: str) -> NoReturn:
    """Exit 2: ``compare`` keeps 1 for "the files differ", as cmp/diff do."""
    print(f"error: {message}", file=sys.stderr)
    sys.exit(2)


def _cmd_compare(args: argparse.Namespace) -> None:
    from ...generators.data.compare import CompareError, compare_files
    from ...generators.data.decoding import RecordDecoder, RecordDecodingError
    from ...layout.errors import CopybookLayoutError

    if args.max_differences is not None and args.max_differences < 0:
        _compare_fail("--max-differences cannot be negative")
    if args.record_length is not None and args.record_length <= 0:
        _compare_fail("--record-length must be a positive number of bytes")
    try:
        decoder = RecordDecoder.from_copybook_file(
            args.copybook,
            record=args.record,
            opts=_decode_encoding_options(args),
            record_length=args.record_length,
            copybook_paths=args.copybook_path or None,
        )
        _warn_layout(decoder.layout_warnings)
        result = compare_files(
            decoder,
            args.expected,
            args.actual,
            view=args.view,
            key=args.key,
            ignore=args.ignore,
            compare_bytes=args.compare_bytes,
            max_differences=args.max_differences,
        )
    except (CompareError, RecordDecodingError, CopybookLayoutError) as exc:
        _compare_fail(str(exc))
    except OSError as exc:
        _compare_fail(f"Cannot read file: {exc}")
    except UnicodeDecodeError as exc:
        # A copybook that is not text (a record file passed as --copybook).
        # Uncaught, the traceback exits 1 -- "the files differ".
        _compare_fail(f"Cannot read copybook {args.copybook}: {exc}")

    if args.output_format == "json":
        text = (
            json.dumps(
                {
                    "expected_file": args.expected,
                    "actual_file": args.actual,
                    "copybook": args.copybook,
                    **result.to_dict(),
                },
                indent=None if args.compact else 2,
            )
            + "\n"
        )
    else:
        text = result.to_text()
    output_path = getattr(args, "output", None)
    if output_path:
        # Not _verbatim_out: its failure exits 1, which here means "differ".
        try:
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as exc:
            _compare_fail(f"Cannot write output file: {exc}")
    else:
        print(text, end="")
    sys.exit(0 if result.equal else 1)


def _build_gen_fixtures_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "gen-fixtures",
        help="Generate program-scoped test fixtures (boundary mocks/asserts) for a COBOL program",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser gen-fixtures INVUPDT.cbl --seed 7 -o fixtures.json\n"
            "  cobol-parser gen-fixtures INVUPDT.cbl --scenarios all --format csv-dir -o fixtures/"
        ),
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_copybook_args(p, strict_flag=True)
    p.add_argument(
        "--callee-path",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory to search for a CALLed program's source, to resolve "
        "CALL argument direction (repeatable)",
    )
    p.add_argument(
        "--rows",
        "-n",
        type=int,
        default=10,
        metavar="N",
        help="Rows to generate per IN file/SQL boundary (default: 10)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="RNG seed for reproducible output (default: random, reported in the bundle)",
    )
    p.add_argument(
        "--max-occurs",
        type=_fixtures_max_occurs,
        default=GEN_FIXTURES_DEFAULT_MAX_OCCURS,
        metavar="N|all",
        help=(
            "Cap the occurrences expanded per OCCURS table (default: "
            f"{GEN_FIXTURES_DEFAULT_MAX_OCCURS}; 'all' expands every one). "
            "Every scenario carries its own fixtures, so an uncapped "
            "OCCURS 160 table multiplies the bundle by the scenario count"
        ),
    )
    p.add_argument(
        "--scenarios",
        choices=["happy", "branches", "all"],
        default="happy",
        help="Scenario strategy: happy (one unconstrained scenario, default), "
        "branches (one scenario per reachable/satisfiable branch arm, merged "
        "where possible), all (branches + fixed empty-input/error-status/"
        "boundary-values families)",
    )
    p.add_argument(
        "--format",
        choices=["json", "csv-dir"],
        default="json",
        help="Output format: one JSON bundle, or one CSV per file boundary "
        "under --output DIR (default: json)",
    )
    p.add_argument(
        "--list-boundaries",
        action="store_true",
        help="List every boundary (category/key/paragraph/line/direction) and exit",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 if the bundle has any unresolved boundary/argument",
    )
    _add_compact_arg(p)
    p.add_argument(
        "--pretty",
        action="store_true",
        help=(
            "Indent the JSON bundle. gen-fixtures writes compact JSON by "
            "default: a bundle runs to megabytes, and indentation alone "
            "adds about a third"
        ),
    )
    p.add_argument(
        "--bundle-version",
        type=int,
        choices=(1, 2),
        default=2,
        help=(
            "JSON bundle shape: 2 (default) writes each distinct fixture once "
            "and has scenarios list fixture ids; 1 repeats every fixture in "
            "every scenario, for a consumer not yet reading version 2"
        ),
    )
    _add_output_arg(p)
    _add_debug_lines_arg(p)
    p.set_defaults(func=_cmd_gen_fixtures)


#: gen-fixtures' default ``--max-occurs``. Uncapped, one program with
#: OCCURS 160 tables and 97 scenarios produced a 1.5 GB bundle.
GEN_FIXTURES_DEFAULT_MAX_OCCURS = 10
#: A bundle larger than this draws a warning naming the levers.
GEN_FIXTURES_SIZE_WARNING_BYTES = 10 * 1024 * 1024


def _fixtures_max_occurs(text: str) -> int | None:
    """``--max-occurs``: a positive count, or ``all`` for no cap."""
    if text.strip().lower() == "all":
        return None
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected a positive number or 'all', got {text!r}"
        ) from exc
    return value


def _capped_tables(ast: Any, cap: int | None) -> list[str]:
    """Names of the OCCURS tables in *ast* with more occurrences than *cap*."""
    if cap is None:
        return []
    names: list[str] = []
    for item in ast.find_all_by_type("DataItem"):
        occurs = getattr(item, "occurs_clause", None)
        times = getattr(occurs, "max_times", None) if occurs is not None else None
        if isinstance(times, int) and times > cap and item.name not in names:
            names.append(item.name)
    return names


def _verification_reasons(verification: dict[str, Any]) -> list[str]:
    """Flatten one scenario's verification verdict into printable reasons.

    Reads the serialized dict rather than the `ScenarioVerification` object
    so this module keeps importing nothing from `generators.verification` --
    the CLI consumes the same shape a bundle consumer would.
    """
    return [
        f"{entry['field']}: {entry['detail']}"
        for entry in verification.get("fields", [])
        if entry.get("status") != "satisfied"
    ] + list(verification.get("gaps", []))


def _warn_unexpanded_copybooks(args: argparse.Namespace, unresolved: list[str]) -> None:
    """One stderr line saying how many COPY members the layout was built
    without (the bundle's `unresolved` names each one)."""
    missing = [n for n in unresolved if " was not expanded; fields it declares" in n]
    if not missing:
        return
    advice = (
        "--strict-copybooks fails instead"
        if args.copybook_path
        else "pass --copybook-path DIR or set project.copybook_path in cobol.yml"
    )
    print(
        f"warning: {args.file}: {len(missing)} copybook(s) not expanded; the "
        f"fixtures cover the program without them (see unresolved; {advice})",
        file=sys.stderr,
    )


def _cmd_gen_fixtures(args: argparse.Namespace) -> None:
    from ...generators.program_fixtures import ProgramFixtureGenerator
    from ...layout.errors import ProgramLayoutError
    from ...preprocess import PreprocessingError

    generator = ProgramFixtureGenerator()
    copybook_paths = args.copybook_path or None
    callee_paths = args.callee_path or None
    debug_lines = bool(getattr(args, "debug_lines", False))
    # Lenient by default, as the analyzers are: a missing COPY member is
    # left out of the layout and named in the bundle's `unresolved` (so
    # --strict still exits 2 on it); --strict-copybooks keeps the old exit 1.
    strict_copybooks = bool(getattr(args, "strict_copybooks", False))

    if args.list_boundaries:
        try:
            _, _, report = generator.analyze_from_file(
                args.file,
                copybook_paths=copybook_paths,
                callee_paths=callee_paths,
                debug_lines=debug_lines,
                strict_copybooks=strict_copybooks,
            )
        except ProgramLayoutError as exc:
            _fail(str(exc))
        except PreprocessingError as exc:
            _fail(f"Copybook expansion failed for {args.file}: {exc}")
        _warn_unexpanded_copybooks(args, report.unresolved)
        _json_out(
            {
                "source_file": args.file,
                "boundaries": [
                    {
                        "category": b.ref.category,
                        "key": b.ref.key,
                        "paragraph": b.ref.paragraph,
                        "line": b.ref.line,
                        "direction": b.direction,
                    }
                    for b in report.boundaries
                ],
            },
            args.compact,
            getattr(args, "output", None),
        )
        return

    from ...layout.options import DataGeneratorOptions

    try:
        options = DataGeneratorOptions(rows=args.rows, max_occurs=args.max_occurs)
    except ValueError as exc:
        # `--rows -1`, `--max-occurs 0` or `data.rows: -5` in cobol.yml: a
        # usage error on one line, as `gen-data` reports it, not a traceback.
        _fail(str(exc))

    try:
        generator = ProgramFixtureGenerator(options)
        # analyze + generate rather than generate_with_scenarios_from_file,
        # whose signature is mocky-mock's contract (interface-contract.md):
        # the same two steps, with debug_lines reaching the parse.
        ast, index, report = generator.analyze_from_file(
            args.file,
            copybook_paths=copybook_paths,
            callee_paths=callee_paths,
            debug_lines=debug_lines,
            strict_copybooks=strict_copybooks,
        )
        bundle = generator.generate_with_scenarios(
            ast, index, report, mode=args.scenarios, seed=args.seed
        )
    except ProgramLayoutError as exc:
        _fail(str(exc))
    except PreprocessingError as exc:
        # A copybook that fails validation (CopybookSyntaxError), cannot be
        # found or expands circularly: one line and exit 1, as `parse` says
        # it, not a traceback.
        _fail(f"Copybook expansion failed for {args.file}: {exc}")

    _warn_unexpanded_copybooks(args, bundle.unresolved)

    # Self-verification summary on stderr (stdout stays JSON-only -- see
    # mockymock's `fixtures` contract). A scenario named for a branch arm
    # whose own generated data does not satisfy that arm is the finding
    # users previously had to discover by running each case under a tracer,
    # so it is worth saying out loud even on a successful run.
    unverified = [
        scenario
        for scenario in bundle.scenarios
        if (scenario.verification or {}).get("status") == "unverified"
    ]
    if unverified:
        print(
            f"warning: {len(unverified)} of {len(bundle.scenarios)} scenario(s) "
            f"could not be verified against their own generated data:",
            file=sys.stderr,
        )
        for scenario in unverified:
            print(f"  {scenario.name}:", file=sys.stderr)
            for reason in _verification_reasons(scenario.verification or {}):
                print(f"    - {reason}", file=sys.stderr)

    if args.strict and bundle.unresolved:
        print(
            f"error: {len(bundle.unresolved)} unresolved item(s) in strict mode:",
            file=sys.stderr,
        )
        for item in bundle.unresolved:
            print(f"  {item}", file=sys.stderr)
        sys.exit(2)

    if args.format == "csv-dir":
        output_dir = getattr(args, "output", None)
        if not output_dir:
            _fail("--format csv-dir requires --output DIR")
        try:
            bundle.write_csv_dir(output_dir)
        except OSError as e:
            _fail(f"Cannot write output directory: {e}")
        return

    capped = _capped_tables(ast, args.max_occurs)
    if capped and args.max_occurs == GEN_FIXTURES_DEFAULT_MAX_OCCURS:
        shown = ", ".join(capped[:5]) + (" ..." if len(capped) > 5 else "")
        print(
            f"note: {len(capped)} OCCURS table(s) capped at "
            f"{args.max_occurs} occurrences by default ({shown}); pass "
            "--max-occurs all to expand every occurrence",
            file=sys.stderr,
        )
    pretty = bool(getattr(args, "pretty", False)) and not args.compact
    text = json.dumps(
        {
            "source_file": args.file,
            **bundle.to_dict(bundle_version=getattr(args, "bundle_version", 2)),
        },
        indent=2 if pretty else None,
    )
    if len(text) > GEN_FIXTURES_SIZE_WARNING_BYTES:
        print(
            f"warning: the bundle is {len(text) / (1024 * 1024):.1f} MB "
            f"({len(bundle.scenarios)} scenario(s)); --max-occurs, --rows "
            "and --scenarios happy make it smaller",
            file=sys.stderr,
        )
    output_path = getattr(args, "output", None)
    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.write("\n")
        except OSError as e:
            _fail(f"Cannot write output file: {e}")
    else:
        print(text)
