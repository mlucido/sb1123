const listings = require('./listings.js');

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

// Filter for southern SFV listings
const sfvListings = listings.filter(l => sfvCities.includes(l.city));

console.log('=== SOUTHERN SAN FERNANDO VALLEY COVERAGE ===\n');
console.log('Total SFV listings:', sfvListings.length);
console.log('\n--- Breakdown by City ---');

sfvCities.forEach(city => {
  const cityListings = sfvListings.filter(l => l.city === city);
  console.log(`${city}: ${cityListings.length}`);
});

// Get unique zip codes
const zipCodes = [...new Set(sfvListings.map(l => l.zip))].sort();
console.log('\n--- Zip Codes Covered ---');
console.log(zipCodes.join(', '));
console.log(`Total unique zip codes: ${zipCodes.length}`);

// Check for SB 1123 criteria listings (12,000 SF+ lot, SFR or Land, not in fire zone)
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

console.log('\n--- Sample Eligible Properties ---');
sb1123Eligible.slice(0, 10).forEach(l => {
  console.log(`${l.address} - ${l.lotSf.toLocaleString()} SF lot - $${l.price.toLocaleString()} - ${l.url}`);
});
