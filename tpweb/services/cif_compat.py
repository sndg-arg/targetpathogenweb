"""Quote bare CIF tokens for older readers without changing their values."""


def quote_bare_cif_tokens(content):
    output = []
    multiline = False
    for line in content.splitlines(keepends=True):
        if line.startswith(";"):
            multiline = not multiline
            output.append(line)
            continue
        if multiline:
            output.append(line)
            continue
        i = 0
        while i < len(line):
            start = i
            if line[i].isspace():
                output.append(line[i])
                i += 1
            elif line[i] == "#":
                output.append(line[i:])
                break
            elif line[i] in "\"'":
                quote = line[i]
                i += 1
                while i < len(line):
                    if line[i] == quote and (i + 1 == len(line) or line[i + 1].isspace()):
                        i += 1
                        break
                    i += 1
                output.append(line[start:i])
            else:
                while i < len(line) and not line[i].isspace():
                    i += 1
                token = line[start:i]
                if "'" in token and '"' not in token:
                    token = '"' + token + '"'
                elif '"' in token and "'" not in token:
                    token = "'" + token + "'"
                # Preserve unusual tokens containing both quote characters;
                # let the reader reject them rather than silently alter data.
                output.append(token)
    return "".join(output)
