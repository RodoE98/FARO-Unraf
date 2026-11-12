/**
 * Convierte la notación LaTeX que escribe el modelo (\( ... \) y \[ ... \]) a la que entiende remark-math
 * ($ ... $ y $$ ... $$).
 *
 * Antes se hacía con .replace(/\\\[/g, "$$"): en JavaScript "$$" dentro de un reemplazo significa UN solo "$",
 * así que las ecuaciones en bloque se mostraban en línea y las anidadas (\( ... \) dentro de \text{...}) rompían la fórmula.
 */
export function prepararMatematica(texto: string): string {
  const DOLAR = "$"; // se arma con una función para evitar los patrones especiales de String.replace ($$, $&, ...)

  // 1) Ecuaciones en bloque: \[ ... \]  ->  $$ ... $$ (en líneas propias).
  //    Dentro de un bloque, un \( ... \) anidado (típico de \text{... \( x \) ...}) pasa a $...$, que KaTeX acepta dentro de \text.
  let t = texto.replace(/\\\[([\s\S]*?)\\\]/g, (_m, interior: string) => {
    const limpio = interior.replace(/\\\(([\s\S]*?)\\\)/g, (_n, x: string) => DOLAR + x.trim() + DOLAR);
    return "\n" + DOLAR + DOLAR + "\n" + limpio.trim() + "\n" + DOLAR + DOLAR + "\n";
  });

  // 2) Fórmulas en línea: \( ... \)  ->  $...$ (sin espacios pegados a los delimitadores, que remark-math no acepta)
  t = t.replace(/\\\(([\s\S]*?)\\\)/g, (_m, interior: string) => DOLAR + interior.trim() + DOLAR);

  // 3) Delimitadores sueltos que quedan durante el streaming (respuesta a medias): se dejan como texto, no rompen el resto.
  return t;
}
