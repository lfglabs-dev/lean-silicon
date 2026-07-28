use std::io::{self, Read};

fn decode_hex(value: &str, expected: usize) -> Result<Vec<u8>, String> {
    if value.len() != expected * 2 {
        return Err(format!("expected {} hex characters", expected * 2));
    }
    (0..expected)
        .map(|i| u8::from_str_radix(&value[2 * i..2 * i + 2], 16)
             .map_err(|_| "invalid hex".to_string()))
        .collect()
}

fn main() -> Result<(), String> {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).map_err(|e| e.to_string())?;
    let fields: Vec<&str> = input.split_whitespace().collect();
    if fields.len() != 5 {
        return Err("expected: BLOCK_HEX CV_HEX COUNTER BLOCK_LEN FLAGS".into());
    }
    let block: [u8; 64] = decode_hex(fields[0], 64)?.try_into().unwrap();
    let cv: [u8; 32] = decode_hex(fields[1], 32)?.try_into().unwrap();
    let counter = fields[2].parse::<u64>().map_err(|e| e.to_string())?;
    let block_len = fields[3].parse::<u32>().map_err(|e| e.to_string())?;
    let flags = fields[4].parse::<u32>().map_err(|e| e.to_string())?;
    if block_len > 64 {
        return Err("block_len exceeds 64".into());
    }
    let digest = blake3_guts::DETECTED_IMPL.compress(
        &block, block_len, &cv, counter, flags,
    );
    for byte in digest {
        print!("{byte:02x}");
    }
    println!();
    Ok(())
}
