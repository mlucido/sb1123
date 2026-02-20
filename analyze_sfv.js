// Load the full listings array
const fs = require('fs');
const content = fs.readFileSync('./listings.js', 'utf8');

// Extract the array - it appears to be a straight JavaScript array declaration
const arrayMatch = content.match(/\[([\s\S]*)\];?$/);
if (!arrayMatch) {
  console.error('Could not parse listings array');
  process.exit(1);
}

const arrayString = '[' + arrayMatch[1] + ']';
const listings = JSON.parse(arrayString);

console.log(`Total listings in file: ${listings.length}`);

// Southern SFV cities
const sfvCities = [
  'Van Nuys',
  'Sherman Oaks',
  'Encino',
  'Tarzana',
  'Woodland Hills',
  'Studio City',
  'Valley Village',
  'North Hollywood',
  'Reseda'
];

// Filter for southern SFV
const sfvListings = listings.filter(l => sfvCities.includes(l.city));

console.log('\n=== SOUTHERN SAN FERNANDO VALLEY COVERAGE ===\n');
console.log('Total SFV listings:', sfvListings.length);
console.log('\n--- Breakdown by City ---');

sfvCities.forEach(city => {
  const cityListings = sfvListings.filter(l => l.city === city);
  console.log(`${city}: ${cityListings.length}`);
});

// Get unique zip codes
const zipCodes = [...new Set(sfvListings.map(l => l.zip))].filter(z => z).sort();
console.log('\n--- Zip Codes Covered ---');
console.log(zipCodes.join(', '));
console.log(`Total unique zip codes: ${zipCodes.length}`);

// SB 1123 eligible properties (12,000 SF+ lot, SFR or Land, not in fire zone)
const sb1123Eligible = sfvListings.filter(l => 
  l.lotSf >= 12000 && 
  (l.type === 'Single Family Residential' || l.type === 'Vacant Land') &&
  l.fireZone === false
);

console.log('\n--- SB 1123 Eligible Properties ---');
console.log(`Total eligible: ${sb1123Eligible.length}`);
console.log('\nBreakdown by city:');
sfvCities.forEach(city => {
  const count = sb1123Eligible.filter(l => l.city === city).length;
  if (count > 0) {
    console.log(`${city}: ${count}`);
  }
});

// Sample properties
console.log('\n--- Sample Eligible Properties (first 15) ---');
sb1123Eligible.slice(0, 15).forEach(l => {
  console.log(`${l.address} - ${l.lotSf.toLocaleString()} SF lot - $${(l.price || 0).toLocaleString()} - ${l.city}`);
});
